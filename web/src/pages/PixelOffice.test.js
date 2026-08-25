import { describe, expect, it } from "vitest";

import { cleanupHudItems, cleanupTotal } from "./PixelOffice.jsx";

describe("Felix cleanup HUD", () => {
  it("shows six applied-work categories and no review or undo counters", () => {
    const items = cleanupHudItems({
      cleanup: {
        names_standardised: 11,
        contact_data_cleaned: 12,
        descriptions_roles_added: 13,
        structured_metadata_added: 14,
        relationships_repaired: 15,
        duplicates_merged: 16,
      },
      recommendations: 99,
      undone: 88,
    });

    expect(items.map(([, value, label]) => [value, label])).toEqual([
      [11, "names standardised"],
      [12, "contact data cleaned"],
      [13, "descriptions and roles added"],
      [14, "structured metadata added"],
      [15, "relationships repaired"],
      [16, "duplicates merged"],
    ]);
    expect(cleanupTotal({ cleanup: {
      names_standardised: 11,
      contact_data_cleaned: 12,
      descriptions_roles_added: 13,
      structured_metadata_added: 14,
      relationships_repaired: 15,
      duplicates_merged: 16,
    } })).toBe(81);
  });
});
