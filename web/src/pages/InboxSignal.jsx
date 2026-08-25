import React from "react";
import { get, post } from "../api.js";
import { Button, ErrorNote, KpiBand, Mascot, PageHeader, useTabScrollMemory } from "../ui.jsx";
import Correspondence from "./inboxSignal/Correspondence.jsx";
import Desk from "./inboxSignal/Desk.jsx";
import Intro from "./inboxSignal/Intro.jsx";
import Managers from "./inboxSignal/Managers.jsx";
import * as signalStore from "./inboxSignal/signalStore.js";
import * as uiStore from "../uiStore.js";

const TABS = [
  { key: "desk", label: "Views from the street" },
  { key: "managers", label: "Manager performance" },
  { key: "log", label: "Correspondence" },
];

const HEADERS = {
  desk: {
    eyebrow: "SHARED INBOX · COLLECTIVE VIEW",
    title: "What the desk is saying",
    desc: "Five sampled windows across the year, read out of the Investments shared mailbox. " +
          "Every quote is verbatim; anything the extractor could not find in the original " +
          "letter is dropped rather than shown.",
  },
  managers: {
    eyebrow: "MANAGER PERFORMANCE · SYSTEMATIC FACTORS",
    title: "Reported figures, and what moves them",
    desc: "Figures managers stated in writing, and the correlation of stored return series " +
          "to five real market factors. Nothing here is generated — where the evidence is " +
          "too thin to support a number, it says so.",
  },
  log: {
    eyebrow: "SHARED INBOX · WHAT WAS SAID",
    title: "Correspondence",
    desc: "The searchable record behind every other view on this page.",
  },
};

export default function InboxSignal() {
  // Held outside React so navigating away and back does not re-buy a payload
  // that takes seconds to build. See signalStore for why.
  React.useSyncExternalStore(signalStore.subscribe, signalStore.getSnapshot);
  const { data, revalidating, loadedAt, error: loadError } = signalStore.state();
  const [jobError, setJobError] = React.useState(null);
  const error = jobError || loadError;
  const [tab, setTab] = React.useState("desk");
  const switchTab = useTabScrollMemory(tab, setTab);
  const [sweeping, setSweeping] = React.useState(false);
  const [reading, setReading] = React.useState(false);
  const [retheming, setRetheming] = React.useState(false);
  // Once per session, like the app's own boot splash — an opening, not a gate.
  // Marked seen on first show rather than on dismissal, so navigating away
  // mid-animation does not bring it back on the next visit.
  const [introUp, setIntroUp] = React.useState(
    () => !sessionStorage.getItem("wb-signal-intro-seen"));

  const load = React.useCallback(() => signalStore.refresh(), []);

  // Renders what is already held and refreshes behind the page; only a cold
  // start shows a loading state.
  React.useEffect(() => { signalStore.ensure(); }, []);

  /* The views rail is drawn by the shell rather than by this page, so it can
     sit flush against the primary navigation instead of inside the content
     column. Each entry carries the size of what it holds, so the rail answers
     "is there anything in there?" without a click. */
  React.useEffect(() => {
    if (!data || introUp) { uiStore.setSubnav(null); return; }
    uiStore.setSubnav({
      title: "Inbox signal",
      active: tab,
      onSelect: switchTab,
      items: TABS.map((t) => ({
        ...t,
        meta: t.key === "desk" ? String((data.themes || []).length)
          : t.key === "managers" ? String((data.reported_returns || []).length)
          : String((data.voices || []).length),
      })),
    });
  }, [data, tab, introUp]);

  /* Unmount clears it. Kept separate from the effect above, whose cleanup would
     otherwise blank the rail on every tab change before re-publishing it. */
  React.useEffect(() => () => uiStore.setSubnav(null), []);

  /* Both background jobs on this page are started and watched the same way:
     fire, then poll until the kind stops reporting a running job, then reload.
     `kind` is the job kind the API registers it under. */
  async function runJob(path, kind, setBusy) {
    setBusy(true);
    try {
      await post(path, {});
      // The job runs on a background thread; poll until it stops reporting as
      // running rather than blocking the page on it.
      const tick = setInterval(async () => {
        try {
          const { jobs } = await get(`/api/jobs?kind=${kind}`);
          if (!jobs.some((j) => j.status === "running")) {
            clearInterval(tick);
            setBusy(false);
            load();
          }
        } catch { clearInterval(tick); setBusy(false); }
      }, 2500);
    } catch (e) {
      setJobError(e.message);
      setBusy(false);
    }
  }

  const runSweep = () => runJob("/api/jobs/inbox-signal", "inbox-signal", setSweeping);
  const runCross = () =>
    runJob("/api/jobs/inbox-signal/cross", "inbox-signal-cross", setReading);
  const runRetheme = () =>
    runJob("/api/jobs/inbox-signal/retheme", "inbox-signal-retheme", setRetheming);

  const head = HEADERS[tab];

  if (error && !data) {
    return (
      <div className="fade-in">
        <PageHeader eyebrow={head.eyebrow} title={head.title} />
        <ErrorNote error={error} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="fade-in">
        <PageHeader eyebrow={head.eyebrow} title={head.title} />
        <Mascot state="reading" width={64} text="Reading the shared inbox…" />
      </div>
    );
  }

  const counts = data.counts || {};
  const sweep = data.sweep || {};
  const last = sweep.last_sweep || {};
  const nothingYet = counts.letters === 0;

  // The opening reads from the payload, so it waits for it rather than
  // announcing counts it does not have yet.
  if (introUp) {
    sessionStorage.setItem("wb-signal-intro-seen", "1");
    return <Intro data={data} onEnter={() => setIntroUp(false)} />;
  }

  return (
    <div className="fade-in">
      <PageHeader
        eyebrow={head.eyebrow}
        title={head.title}
        actions={
          <>
            {/* Held figures are labelled as held. The page renders instantly
                from cache on a return visit, and saying nothing would let a
                stale reading pass as a fresh one. */}
            {revalidating && (
              <span className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                    textTransform: "uppercase", color: "var(--stone-400)",
                    alignSelf: "center" }}>
                Refreshing
              </span>
            )}
            <Button variant="ghost" onClick={() => setIntroUp(true)}>Replay intro</Button>
            <Button variant="ghost" onClick={runSweep} busy={sweeping}>
              {sweeping ? "Sweeping…" : "Sweep inbox"}
            </Button>
          </>
        }
      >
        {head.desc}
      </PageHeader>

      <KpiBand items={[
        ["MANAGERS HEARD FROM", counts.organisations || 0],
        ["LETTERS READ", counts.letters || 0],
        ["QUOTES HELD", counts.quotes || 0],
        ["AWAITING A READ", sweep.attachments_pending || 0, (sweep.attachments_pending || 0) > 0,
         (sweep.attachments_pending || 0) > 0 ? "track records needing Graph access" : ""],
      ]} />

      {nothingYet && (
        <div style={{ borderTop: "1px solid var(--paper-200)", borderBottom: "1px solid var(--paper-200)",
                      padding: "18px 0", margin: "0 0 22px" }}>
          <Mascot
            state="confused"
            width={54}
            text={"No correspondence has been extracted yet. Put a snapshot of the shared mailbox " +
                  "at data/shared_inbox_snapshot.json (see scripts/refresh_shared_inbox_snapshot.py), " +
                  "then press Sweep inbox."} />
        </div>
      )}

      {tab === "desk" && <Desk data={data} onReadAcross={runCross} reading={reading} />}
      {tab === "managers" && <Managers data={data} />}
      {tab === "log" && (
        <Correspondence data={data} onRetheme={runRetheme} retheming={retheming} />
      )}

      {/* The standing note on what this page is and is not. It sits under every
          view rather than inside one, because the commitments it describes —
          verbatim quotes, stated figures, no demo data — govern all of them. */}
      <footer style={{ marginTop: 38, borderTop: "1px solid var(--paper-200)",
                       paddingTop: 16 }}>
        <span className="microlabel">HOW TO READ THIS PAGE</span>
        <p className="muted" style={{ fontSize: 12, lineHeight: 1.6, margin: "8px 0 0",
                                      maxWidth: 860 }}>
          Every quote is a verbatim span from a real message; any the extractor could not find
          in the original letter is dropped rather than shown. Every figure is one a manager
          stated in writing for a named month — nothing is computed, annualised or inferred
          from it. Stance is the posture of a whole letter toward risk, not a verdict on any
          one theme within it, which is why themes carry a breakdown rather than a label.
          Silence is reported as silence: a manager who did not write is a gap, not a neutral.
          There is no demo mode anywhere on this page — where the evidence is too thin to
          support a number, it says so instead of showing one.
        </p>
        {last.messages_seen !== undefined && (
          <p className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
            Last sweep saw {last.messages_seen} messages, {last.already_known || 0} already read,
            and extracted {last.letters || 0}
            {last.quotes_dropped ? ` · ${last.quotes_dropped} quotes dropped as unverifiable` : ""}
            {last.remaining ? ` · ${last.remaining} still queued` : ""}.
            {data.coverage ? ` Coverage: ${data.coverage}.` : ""}
          </p>
        )}
      </footer>
    </div>
  );
}
