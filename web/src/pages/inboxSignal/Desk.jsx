import React from "react";
import { Button, Card, SectionHead, useScrollHold } from "../../ui.jsx";
import {
  Band, BandLabel, Drawer, DriftGrid, Empty, PeriodScrubber, QuoteBlock,
  STANCE_COLOR, STANCE_LABEL, STANCE_ORDER, STANCE_SURFACE, STANCE_TONE, STANCE_WITH_A_VIEW,
  StanceBar, ThemeCloud,
} from "./shared.jsx";

/* How many themes the drift grid carries. Forty-eight themes is a wall of
   rows in which nothing stands out, and the tail is mostly themes raised once.
   The count omitted is always stated underneath — a silent cut reads as
   "this is all of them". */
const DRIFT_ROWS = 14;
/* Themes below this many mentions across the year stay out of the cloud unless
   the selected window raised them, so a one-off does not sit at the same visual
   weight as a running concern. */
const CLOUD_FLOOR = 12;
/* Quotes shown per letter before the rest are left to the Correspondence tab.
   One letter can carry six verified spans, which buries the next correspondent
   under a single manager's column. The remainder is always counted, never
   silently dropped. */
const QUOTES_PER_LETTER = 3;

/* "Views from the street" — what the desk collectively says, and how it moved. */
export default function Desk({ data, onReadAcross, reading }) {
  const periods = data.mailbox_periods || [];
  const themes = data.themes || [];
  const voices = data.voices || [];
  const stanceByOrg = data.stance_by_org || [];
  const matrix = data.stance_matrix || { cols: [], rows: [] };
  const cross = data.cross || {};

  // Position runs 0…(n−1)×100; see PeriodScrubber for why it is not 0…n−1.
  const lastPos = Math.max(0, (periods.length - 1) * 100);
  const [pos, setPos] = React.useState(lastPos);
  const [openTheme, setOpenTheme] = React.useState(null);
  // Switching lookback windows swaps the cloud and the quotes below for a
  // different amount of content; hold the scroll through it (see useScrollHold).
  const hold = useScrollHold();

  // The window opens on the most recent sample. If a sweep lands and changes
  // how many windows carry letters, follow it rather than stranding the thumb.
  React.useEffect(() => { setPos(lastPos); }, [lastPos]);

  if (!periods.length) {
    return (
      <div className="fade-in">
        <Empty>
          No sampled windows yet. The five windows are fixed constants — they fill in
          as the sweep reads the shared mailbox.
        </Empty>
      </div>
    );
  }

  const index = Math.min(periods.length - 1, Math.max(0, Math.round(pos / 100)));
  const lo = Math.min(periods.length - 1, Math.floor(pos / 100));
  const hi = Math.min(periods.length - 1, lo + 1);
  const frac = pos / 100 - lo;
  const period = periods[index];

  // ---- Cloud: everything raised in this window, plus the year's main themes
  //      so a theme going quiet is visible as a fade rather than a deletion.
  const cloudThemes = themes
    .filter((t) => t.series[index] > 0 || t.total >= CLOUD_FLOOR)
    .sort((a, b) => (b.series[index] || 0) - (a.series[index] || 0) || b.total - a.total);
  const hiddenThemes = themes.length - cloudThemes.length;

  // ---- Voices in this window, grouped by stance then by organisation.
  const windowVoices = voices.filter((v) => v.period === period.key);

  const stanceAt = (org, i) => {
    const row = stanceByOrg.find((r) => r.org === org);
    return row ? row.stances[i] : null;
  };
  /* The last window this organisation actually wrote in — not simply the
     previous window, which for a quarterly correspondent is almost always
     silence and would report every letter as a change of mind. */
  const previously = (org) => {
    for (let j = index - 1; j >= 0; j--) {
      const s = stanceAt(org, j);
      if (s) return { stance: s, when: periods[j].short };
    }
    return null;
  };

  /* Grouped by letter, not by organisation: a manager who wrote twice in one
     window wrote two letters, and merging them would file both sets of quotes
     under whichever subject line happened to come first.

     Neutral letters are left out. This section exists to show what managers
     think, and a neutral letter is by definition one that reported without
     thinking anything out loud — the eight in one window read "the fund made
     a net return of -12.22% MTD" and "we will circulate the official
     factsheet around 12th August", which are facts the figures already carry.
     They are still counted below and still searchable in the log. */
  const neutralLetters = new Set(
    windowVoices.filter((v) => v.stance === "neutral")
      .map((v) => `${v.org}|${v.person}|${v.source}`));

  const groups = STANCE_WITH_A_VIEW.map((stance) => {
    const mine = windowVoices.filter((v) => v.stance === stance);
    const letters = [];
    mine.forEach((v) => {
      let slot = letters.find((g) => g.org === v.org && g.person === v.person
                                     && g.source === v.source);
      if (!slot) {
        slot = { org: v.org, person: v.person, source: v.source, date: v.date, quotes: [] };
        letters.push(slot);
      }
      slot.quotes.push(v);
    });
    letters.forEach((g) => {
      const prev = previously(g.org);
      g.moved = prev && prev.stance !== stance ? prev : null;
    });
    return { stance, letters, count: mine.length };
  }).filter((g) => g.letters.length);

  const movedCount = groups.reduce((n, g) => n + g.letters.filter((o) => o.moved).length, 0);
  const shownQuotes = groups.reduce((n, g) => n + g.count, 0);
  // Counted over what is shown, so the sentence beneath the heading does not
  // claim managers whose only letter was dropped as neutral.
  const quotedOrgs = new Set(
    windowVoices.filter((v) => v.stance !== "neutral").map((v) => v.org)).size;

  // ---- Theme drawer
  const active = themes.find((t) => t.id === openTheme) || null;
  const inTheme = (v) => (v.themes || []).includes(openTheme);
  const drawerNow = active ? windowVoices.filter(inTheme) : [];
  const drawerElse = active
    ? voices.filter((v) => v.period !== period.key && inTheme(v))
    : [];

  const driftThemes = themes.slice(0, DRIFT_ROWS);

  return (
    <div className="fade-in">
      <PeriodScrubber periods={periods} pos={pos}
                      onPos={(p) => hold(() => setPos(p))} index={index} />

      <Band>
        <BandLabel label="MOVES WITH THE LOOKBACK">
          Everything in this band is scoped to {period.label}. Everything below it covers{" "}
          {data.coverage || "the whole year"}.
        </BandLabel>

        <SectionHead
          label="THE CONVERSATION, SIZED"
          right={period.letters
            ? `${cloudThemes.filter((t) => t.series[index] > 0).length} RAISED · ${period.letters} LETTERS`
            : ""} />

        {period.letters === 0 ? (
          <Empty>
            No letters were extracted from {period.label}. Either nothing substantive arrived
            in that window, or the sweep has not reached it — the header's counts say which.
          </Empty>
        ) : (
          <Card style={{ padding: "22px 24px" }}>
            <ThemeCloud
              themes={cloudThemes} periods={periods} index={index}
              frac={frac} lo={lo} hi={hi}
              selected={openTheme} onSelect={setOpenTheme} />

            <div className="muted" style={{ fontSize: 12, lineHeight: 1.55, marginTop: 20,
                                            paddingTop: 14, borderTop: "1px solid var(--paper-200)" }}>
              Size is the theme's share of this window's {period.letters}{" "}
              {period.letters === 1 ? "letter" : "letters"}; the figure is the letter count and
              a dash means it was not raised here. The bar beneath each term is how the managers
              raising it were positioned overall — a breakdown, not a verdict on the theme.
              Select any term to read the letters behind it.
              {hiddenThemes > 0 && ` ${hiddenThemes} further ${hiddenThemes === 1 ? "theme" : "themes"} \
were raised fewer than ${CLOUD_FLOOR} times across the year and only appear in the windows that raised them.`}
            </div>
          </Card>
        )}

        <SectionHead label="IN THEIR WORDS"
                     right={shownQuotes ? `${shownQuotes} QUOTES` : ""}
                     style={{ paddingTop: 28 }} />

        {shownQuotes === 0 ? (
          <Empty>
            {windowVoices.length === 0
              ? "No quotes held from this window."
              : "Every letter in this window reported without taking a position. The figures "
                + "are on the manager performance tab; the letters themselves are in the log."}
          </Empty>
        ) : (
          <>
            <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: "0 0 14px" }}>
              Grouped by the stance of the letter, so the balance of the window reads at a glance.
              Quoted here are {quotedOrgs} of the window's {period.orgs}{" "}
              {period.orgs === 1 ? "manager" : "managers"} — the rest wrote without a line the
              extractor could verify against the source body.
              {movedCount > 0
                ? ` ${movedCount} ${movedCount === 1 ? "correspondent has" : "correspondents have"} \
changed stance since the last window they wrote in — marked in brass.`
                : " No correspondent changed stance since the last window they wrote in."}
              {neutralLetters.size > 0
                && ` ${neutralLetters.size} further ${neutralLetters.size === 1
                  ? "letter reported" : "letters reported"} without taking a position and \
${neutralLetters.size === 1 ? "is" : "are"} not shown — searchable in the correspondence log.`}
            </p>

            <div style={{ display: "grid", gap: 26,
                          gridTemplateColumns: "repeat(auto-fit,minmax(290px,1fr))",
                          alignItems: "start" }}>
              {groups.map((g) => (
                <section key={g.stance} style={{ minWidth: 0 }}>
                  {/* The column head is the one thing that has to survive a
                      skim — it is what tells you the balance of the window.
                      Tinted, boxed and set at reading size rather than as a
                      micro-label, so the three stances register as three
                      distinct columns before any quote is read. */}
                  <div className="spread mono" style={{
                    alignItems: "center", padding: "8px 11px", marginBottom: 4,
                    background: STANCE_SURFACE[g.stance],
                    borderLeft: `3px solid ${STANCE_COLOR[g.stance]}`,
                    borderBottom: `2px solid ${STANCE_COLOR[g.stance]}`,
                    borderRadius: "var(--radius) var(--radius) 0 0",
                    fontSize: 12.5, fontWeight: 600, letterSpacing: ".1em",
                    textTransform: "uppercase", color: STANCE_COLOR[g.stance],
                  }}>
                    <span>{STANCE_LABEL[g.stance]}</span>
                    <span style={{ fontSize: 15, letterSpacing: 0 }}>{g.count}</span>
                  </div>

                  {g.letters.map((o, i) => {
                    const shown = o.quotes.slice(0, QUOTES_PER_LETTER);
                    const rest = o.quotes.length - shown.length;
                    return (
                      <article key={`${o.org}-${i}`} style={{
                        padding: o.moved ? "13px 0 13px 12px" : "13px 0",
                        marginLeft: o.moved ? -12 : 0,
                        borderBottom: "1px solid var(--paper-200)",
                        borderLeft: o.moved ? "2px solid var(--brass-500)" : "none",
                      }}>
                        <div className="spread" style={{ alignItems: "baseline" }}>
                          <b style={{ fontSize: 13.5 }}>{o.org}</b>
                          <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>
                            {o.date}
                          </span>
                        </div>
                        {o.person && (
                          <div className="muted" style={{ fontSize: 12 }}>{o.person}</div>
                        )}
                        {o.moved && (
                          <span className="chip brass" style={{ marginTop: 6 }}>
                            was {STANCE_LABEL[o.moved.stance].toLowerCase()} in {o.moved.when}
                          </span>
                        )}
                        {shown.map((v, qi) => (
                          <blockquote key={qi} style={{
                            margin: "9px 0 0", paddingLeft: 12,
                            borderLeft: "2px solid var(--teal-300)",
                            font: "400 14px/1.55 var(--serif)", color: "var(--ink-800)",
                          }}>
                            “{v.quote}”
                          </blockquote>
                        ))}
                        {rest > 0 && (
                          <div className="muted" style={{ fontSize: 12, marginTop: 7 }}>
                            +{rest} further {rest === 1 ? "quote" : "quotes"} from this letter —
                            all of them are on the Correspondence tab.
                          </div>
                        )}
                        <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                                                       textTransform: "uppercase",
                                                       color: "var(--stone-400)", marginTop: 7 }}>
                          {o.source}
                        </div>
                      </article>
                    );
                  })}
                </section>
              ))}
            </div>
          </>
        )}
      </Band>

      <BandLabel label="ACROSS THE WHOLE YEAR" tone="var(--stone-500)"
                 style={{ marginTop: 30 }}>
        Fixed. The lookback does not change anything from here down.
      </BandLabel>

      <SectionHead label="HOW EACH THEME ENTERED THE ROOM"
                   right={`TOP ${Math.min(DRIFT_ROWS, themes.length)} BY MENTIONS`} />
      {themes.length === 0 ? (
        <Empty>
          No themes yet — they are counted from extracted letters, so run a sweep
          from the header once the shared-inbox snapshot is in place.
        </Empty>
      ) : (
        <Card style={{ overflowX: "auto", padding: "18px 20px" }}>
          <DriftGrid themes={driftThemes} periods={periods} />
          <p className="muted" style={{ fontSize: 12, lineHeight: 1.55, margin: "14px 0 0" }}>
            Depth of tint is the theme's share of that window's letters, so a busy window and a
            quiet one compare honestly. Direction compares the first and last sample only.
            {themes.length > DRIFT_ROWS &&
              ` ${themes.length - DRIFT_ROWS} further themes fall below the top ${DRIFT_ROWS} and are not shown here; all of them are filterable on the Correspondence tab.`}
          </p>
        </Card>
      )}

      <ReadAcross cross={cross} onRun={onReadAcross} running={reading} />

      {/* The watchlist moved to the Manager performance tab: it is built from
          reported drawdowns, silences and unreadable track records, so it reads
          the same figures that tab shows. */}

      {matrix.rows.length > 0 && (
        <>
          <SectionHead label="WHO IS ENGAGING WITH WHAT" style={{ paddingTop: 30 }} />
          <Card style={{ overflowX: "auto", padding: "18px 20px" }}>
            <table className="wb">
              <thead>
                <tr>
                  <th>Manager</th>
                  {matrix.cols.map((c) => <th key={c}>{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {matrix.rows.map((r) => (
                  <tr key={r.org}>
                    <td>{r.org}</td>
                    {r.cells.map((cell, i) => (
                      <td key={i} style={{
                        color: cell === "+" ? "var(--positive-600)"
                             : cell === "~" ? "var(--caution-600)" : "var(--paper-300)",
                        fontSize: cell ? 15 : 13,
                      }}>
                        {cell || "·"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
              <b style={{ color: "var(--positive-600)" }}>+</b> engaged constructively ·{" "}
              <b style={{ color: "var(--caution-600)" }}>~</b> engaged with caution ·{" "}
              <b style={{ color: "var(--stone-500)" }}>·</b> did not raise it
            </p>
          </Card>
        </>
      )}

      <Drawer
        open={!!active} onClose={() => setOpenTheme(null)}
        eyebrow="THEME" title={active ? active.label : ""}>
        {active && (
          <>
            <div className="row" style={{ gap: 5, marginBottom: 4 }}>
              {STANCE_ORDER.filter((s) => (active.stances || {})[s]).map((s) => (
                <span key={s} className={`chip ${STANCE_TONE[s] || "neutral"}`}>
                  {active.stances[s]} {STANCE_LABEL[s]}
                </span>
              ))}
            </div>
            <StanceBar stances={active.stances} height={5} />

            <div className="muted" style={{ fontSize: 12.5, margin: "14px 0 6px" }}>
              {active.series[index]
                ? `${active.series[index]} of ${period.letters} letters raise it in ${period.label} · ${active.total} across the year`
                : `Not raised in ${period.label} · ${active.total} across the year`}
            </div>

            <span className="microlabel" style={{ display: "block", marginTop: 16 }}>
              LETTERS BY WINDOW — SELECT TO MOVE THE LOOKBACK
            </span>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${periods.length},minmax(0,1fr))`,
                          marginTop: 6 }}>
              {periods.map((p, i) => (
                <button type="button" key={p.key} onClick={() => setPos(i * 100)}
                        style={{ background: "none", cursor: "pointer", padding: "8px 2px",
                                 border: "none",
                                 borderTop: i === index ? "2px solid var(--brass-500)"
                                                        : "1px solid var(--paper-200)",
                                 display: "flex", flexDirection: "column", gap: 3,
                                 alignItems: "center" }}>
                  <span className="mono" style={{ fontSize: 16,
                                                  color: active.series[i] ? "var(--ink-700)" : "var(--stone-400)" }}>
                    {active.series[i] || "—"}
                  </span>
                  <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".1em",
                                                  textTransform: "uppercase",
                                                  color: i === index ? "var(--brass-700)" : "var(--stone-400)" }}>
                    {p.short}
                  </span>
                </button>
              ))}
            </div>

            {drawerNow.length > 0 && (
              <div style={{ marginTop: 22 }}>
                <span className="microlabel" style={{ color: "var(--brass-700)" }}>
                  {period.label.toUpperCase()}
                </span>
                {drawerNow.map((v, i) => <QuoteBlock key={i} v={v} />)}
              </div>
            )}

            {drawerElse.length > 0 && (
              <div style={{ marginTop: 22 }}>
                <span className="microlabel">
                  ELSEWHERE IN THE YEAR — {drawerElse.length}{" "}
                  {drawerElse.length === 1 ? "QUOTE" : "QUOTES"}
                </span>
                {drawerElse.map((v, i) => <QuoteBlock key={i} v={v} dim />)}
              </div>
            )}

            {drawerNow.length === 0 && drawerElse.length === 0 && (
              <Empty>
                This theme was tagged on a letter, but no quote held against it survived
                verification against the source body.
              </Empty>
            )}
          </>
        )}
      </Drawer>
    </div>
  );
}

/* Where a manager contradicted themselves, and where two of them contradict
   each other. Unlike everything else on this page these are model judgements
   over pairs of letters, not counts — so they arrive only when the pass has
   been run, and the coverage line says how much ground is still unread rather
   than letting a thin section pass for a quiet desk. */
function ReadAcross({ cross, onRun, running }) {
  const reversals = cross.reversals || [];
  const conflicts = cross.conflicts || [];
  const found = reversals.length + conflicts.length;
  const pending = cross.pending || 0;
  const candidates = cross.candidates || 0;
  const read = candidates - pending;

  return (
    <>
      <SectionHead
        label="WHERE THE DESK CONTRADICTS ITSELF"
        right={!candidates ? ""
          : read === 0 ? `${candidates} PAIRS TO READ`
          : `${found} FROM ${read} PAIRS READ`}
        style={{ paddingTop: 30 }}
      />

      <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: "0 0 14px" }}>
        Pairs of letters that look opposed — one manager across two windows, or two managers
        in one — read together and adjudicated. Most candidates turn out not to be
        contradictions at all, and a rejected pair is remembered so it is never re-read.
        {candidates > 0 && pending > 0
          && ` ${pending} of ${candidates} ${pending === 1 ? "pair is" : "pairs are"} still unread.`}
        {cross.not_examined > 0
          && ` A further ${cross.not_examined} opposed pairings fall outside the most-evidenced few per theme and window, and were not put up.`}
      </p>

      {onRun && (
        <div style={{ marginBottom: 16 }}>
          <Button variant="ghost" onClick={onRun} busy={running} disabled={running || !pending}>
            {running ? "Reading across…"
              : pending ? `Read the ${pending} unread ${pending === 1 ? "pair" : "pairs"}`
              : "Nothing left to read"}
          </Button>
        </div>
      )}

      {found === 0 ? (
        <Empty>
          {/* Four different states, and they mean different things. "Nothing
              found" after reading nothing is not the same claim as "nothing
              found" after reading everything. */}
          {candidates === 0
            ? "No opposed pairs to read yet — they need two letters from one manager on one theme, or two managers taking opposite sides of it in the same window."
            : read === 0
              ? `Nothing read yet. ${candidates} candidate ${candidates === 1 ? "pair is" : "pairs are"} waiting, and each one costs a model call.`
              : pending > 0
                ? `${read} ${read === 1 ? "pair" : "pairs"} read so far, ${read === 1 ? "and it was not" : "and none was"} a real contradiction — ${pending} still to read.`
                : "Every candidate pair has been read, and none was a real contradiction. Two managers labelled with opposing stances while writing about different holdings is the common case, which is why the pairs are read rather than counted."}
        </Empty>
      ) : (
        <div style={{ display: "grid", gap: 14,
                      gridTemplateColumns: "repeat(auto-fit,minmax(400px,1fr))" }}>
          {reversals.map((r) => (
            <Card key={r.key} style={{ borderLeft: "3px solid var(--brass-500)" }}>
              <div className="spread" style={{ alignItems: "baseline" }}>
                <b style={{ fontSize: 14 }}>{r.org}</b>
                <span className="chip brass">Changed position</span>
              </div>
              <span className="microlabel">
                {r.theme_label} · {r.earlier?.period_label} → {r.later?.period_label}
              </span>
              <p style={{ font: "400 14px/1.45 var(--serif)", color: "var(--ink-800)",
                          margin: "6px 0 10px" }}>
                {r.summary}
              </p>
              <Side v={r.earlier} label="THEN" />
              <Side v={r.later} label="NOW" />
              <Confidence value={r.confidence} />
            </Card>
          ))}
          {conflicts.map((c) => (
            <Card key={c.key} style={{ borderLeft: "3px solid var(--teal-500)" }}>
              <div className="spread" style={{ alignItems: "baseline" }}>
                <b style={{ fontSize: 14 }}>{c.a?.org} vs {c.b?.org}</b>
                <span className="chip">{c.period_label}</span>
              </div>
              <span className="microlabel">{c.theme_label}</span>
              <p style={{ font: "400 14px/1.45 var(--serif)", color: "var(--ink-800)",
                          margin: "6px 0 4px" }}>
                {c.question}
              </p>
              <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, margin: "0 0 10px" }}>
                {c.summary}
              </p>
              <Side v={c.a} label={c.a?.org} />
              <Side v={c.b} label={c.b?.org} />
              <Confidence value={c.confidence} />
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

/* One side of a pair. The quote is not written by the model — it picks one of
   the letter's already-verified spans by number — so what shows here is text
   the manager wrote, same as everywhere else on the page. */
function Side({ v, label }) {
  if (!v?.quote) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div className="spread" style={{ alignItems: "baseline" }}>
        <span className="microlabel">{label}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)" }}>{v.date}</span>
      </div>
      <blockquote style={{ margin: "4px 0 0", paddingLeft: 12,
                           borderLeft: "2px solid var(--teal-300)",
                           font: "400 13.5px/1.5 var(--serif)", color: "var(--ink-800)" }}>
        “{v.quote}”
      </blockquote>
      {v.source && (
        <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                                       textTransform: "uppercase", color: "var(--stone-400)",
                                       marginTop: 5 }}>
          {v.source}
        </div>
      )}
    </div>
  );
}

function Confidence({ value }) {
  if (!value) return null;
  return (
    <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                                   textTransform: "uppercase", color: "var(--stone-400)",
                                   marginTop: 10, paddingTop: 8,
                                   borderTop: "1px solid var(--paper-200)" }}>
      {value} confidence in this reading
    </div>
  );
}
