import React from "react";

/* Navigation icons.

   Line drawings on a 24px grid, stroked in ``currentColor`` so a single rule
   colours them with their label — the sidebar's hover and active states then
   need no icon-specific CSS at all.

   They exist because the primary rail collapses to icons whenever a page
   brings its own sub-navigation. At 64px wide there is no room for words, so
   the icon stops being decoration and becomes the only way to tell Triage from
   Prep. That is also why each one is a distinct silhouette rather than a set of
   variations on a rounded square: recognition at a glance is the whole job.
*/

const PATHS = {
  home: "M3 10.5 12 3l9 7.5M5.5 9.5V21h13V9.5",
  triage: "M3 13h5l1.5 2.5h5L16 13h5M3 13l3-8h12l3 8v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  prep: "M9 4h6v3H9zM7 5.5H5.5A1.5 1.5 0 0 0 4 7v13a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 20V7a1.5 1.5 0 0 0-1.5-1.5H17M8 12h8M8 16h5",
  live: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11v1a7 7 0 0 0 14 0v-1M12 19v3",
  signal: "M2 12h4l3-8 4 16 3-8h6",
  // A radial spider-web: hub, four spokes, and a ring segment between them.
  cweb: "M12 12m-1.5 0a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0M12 10.5V3M13.5 12H21M12 13.5V21M10.5 12H3M12 6a6 6 0 0 1 6 6M12 18a6 6 0 0 1-6-6",
  track: "M4 4v16h16M8 15l3.5-4L15 14l4-6",
  funds: "M12 3 3 7.5 12 12l9-4.5zM3 12.5 12 17l9-4.5M3 17 12 21.5 21 17",
  news: "M4 5h11v15H5a1 1 0 0 1-1-1zM15 9h4a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-4M7 8h5M7 11h5M7 14h5",
  felix: "M15.5 3.5a5 5 0 0 0-5.9 6.4L3.4 16a2 2 0 1 0 2.8 2.8l6.1-6.1a5 5 0 0 0 6.3-6l-3 3-2.4-.6-.6-2.4z",
  contact: "M15 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM18 8v6M21 11h-6",
  travel: "M4 19.5h16M6 17l2-5 4 2 3-7 3 10M12 4.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
};

export default function Icon({ name, size = 18 }) {
  const d = PATHS[name];
  if (!d) return null;
  return (
    <svg className="navicon" width={size} height={size} viewBox="0 0 24 24"
         fill="none" stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}
