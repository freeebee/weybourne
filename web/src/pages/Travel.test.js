import { describe, expect, it } from "vitest";
import {
  candidateMatchesQuery, candidateSignalChips, filterTravelCandidates,
  isManagerRow, travelMapPoints,
} from "./Travel.jsx";

const candidates = [
  { id: "a", company_id: "co-a", company: "Alpha", city: "London", country: "UK",
    office: { latitude: 51.5, longitude: -.1 } },
  { id: "b", company_id: "co-b", company: "Beta", city: "New York", country: "US",
    office: { latitude: 40.7, longitude: -74 } },
];

describe("travel planner view models", () => {
  it("filters suggested meetings by country or manager anchor", () => {
    expect(filterTravelCandidates(candidates, { type: "country", id: "UK" }).map((x) => x.id)).toEqual(["a"]);
    expect(filterTravelCandidates(candidates, { type: "manager", id: "co-b" }).map((x) => x.id)).toEqual(["b"]);
    expect(filterTravelCandidates(candidates, { type: "manager", id: "co-a", city: "London", country: "UK" }).map((x) => x.id)).toEqual(["a"]);
  });

  it("click visibility controls manager markers while the selected hotel remains", () => {
    const trip = { candidates, hotels: [{ id: "h", name: "Hotel", selected: true,
      latitude: 51.51, longitude: -.11 }] };
    expect(travelMapPoints(trip, new Set(["a"])).map((x) => [x.id, x.kind]))
      .toEqual([["a", "office"], ["h", "hotel"]]);
    expect(travelMapPoints(trip, new Set()).map((x) => x.id)).toEqual(["h"]);
  });

  it("derives signal chips: status and quality tags, recco and note counts", () => {
    const chips = candidateSignalChips({
      status: "Track", quality: "High", reccos: 3,
      recommenders: ["Lena Park", "Omar Reyes"], notes: 12, last_note: "2026-06-12",
    });
    expect(chips.map((c) => c.text)).toEqual(["TRACK", "HIGH QUALITY", "RECCOS · 3", "NOTES · 12"]);
    expect(chips[2].hint).toBe("Recommended by Lena Park, Omar Reyes and others");
    expect(chips[3].hint).toBe("Last note 2026-06-12");
  });

  it("search matches the funds behind a manager row, and manager rows are recognised", () => {
    const row = { id: "company-co-a", name: "Advantage Partners", company: "Advantage Partners",
      city: "Tokyo", country: "Japan", email: "",
      signals: { funds: ["Advantage Partners Asia Fund II"] } };
    expect(candidateMatchesQuery(row, "asia fund")).toBe(true);
    expect(candidateMatchesQuery(row, "tokyo")).toBe(true);
    expect(candidateMatchesQuery(row, "zephyr")).toBe(false);
    expect(candidateMatchesQuery({ id: "p1", name: "Ada" }, "ada")).toBe(true);
    expect(isManagerRow(row)).toBe(true);
    expect(isManagerRow({ id: "0f3a-notion-uuid" })).toBe(false);
  });

  it("invested reads as brass; weak or missing signals stay silent", () => {
    expect(candidateSignalChips({ status: "Invested", quality: "Medium", reccos: 0, notes: 0 }))
      .toEqual([{ text: "INVESTED", tone: "brass" }]);
    expect(candidateSignalChips({ status: "Met", quality: "Low", reccos: 0, notes: 0 })).toEqual([]);
    expect(candidateSignalChips(null)).toEqual([]);
  });
});
