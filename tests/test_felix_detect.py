"""Felix's deterministic detection core — the safety net for everything the
agent decides without a model in the loop."""
from src.features.felix import detect


def page(pid, db="contacts", name="", email="", relations=None, icon=None,
         extra_props=None, created="2026-01-01T00:00:00.000Z", archived=False):
    props = {"Name": {"type": "title", "title": [{"plain_text": name}]}}
    if email is not None:
        props["Email"] = {"type": "email", "email": email or None}
    for prop, ids in (relations or {}).items():
        props[prop] = {"type": "relation",
                       "relation": [{"id": i} for i in ids], "has_more": False}
    props.update(extra_props or {})
    return {"id": pid, "url": f"https://notion.so/{pid}", "icon": icon,
            "archived": archived, "created_time": created,
            "last_edited_time": created, "properties": props}


def card(*args, **kw):
    db = kw.pop("db", "contacts")
    return detect.card_from_page(page(*args, db=db, **kw), db)


class TestCards:
    def test_card_normalises(self):
        c = card("p1", name="Allan Fife", email="Allan@FifeCapital.com.au",
                 relations={"Employed By": ["co1"]})
        assert c["name"] == "Allan Fife"
        assert c["email"] == "allan@fifecapital.com.au"
        assert c["domain"] == "fifecapital.com.au"
        assert c["relations"]["Employed By"] == ["co1"]
        assert c["title_prop"] == "Name"


class TestFingerprint:
    """card_fingerprint gates the adjudication cache: unchanged fingerprint
    means the cached verdict is still good, so this is what actually decides
    whether a pair gets re-adjudicated or skipped."""

    def test_identical_cards_fingerprint_the_same(self):
        a = card("a", name="Allan Fife", email="allan@fife.com")
        b = card("b", name="Allan Fife", email="allan@fife.com")
        assert detect.card_fingerprint(a) == detect.card_fingerprint(b)

    def test_a_changed_name_changes_the_fingerprint(self):
        a = card("a", name="Allan Fife", email="allan@fife.com")
        b = card("a", name="Alan Fife", email="allan@fife.com")
        assert detect.card_fingerprint(a) != detect.card_fingerprint(b)

    def test_a_changed_relation_changes_the_fingerprint(self):
        a = card("a", name="Allan Fife", relations={"Employed By": ["co1"]})
        b = card("a", name="Allan Fife", relations={"Employed By": ["co2"]})
        assert detect.card_fingerprint(a) != detect.card_fingerprint(b)

    def test_last_edited_time_alone_does_not_change_it(self):
        # An icon tweak or an unrelated field bumps last_edited_time but must
        # not, by itself, invalidate a cached adjudication verdict — the
        # fingerprint is deliberately NOT built from it.
        a = card("a", name="Allan Fife", email="allan@fife.com",
                created="2026-01-01T00:00:00.000Z")
        b = card("a", name="Allan Fife", email="allan@fife.com",
                created="2026-06-01T00:00:00.000Z")
        assert detect.card_fingerprint(a) == detect.card_fingerprint(b)


class TestExactDuplicates:
    def test_same_email_grouped(self):
        cards = [card("a", name="Allan Fife", email="a@fife.com"),
                 card("b", name="Alan Fyfe", email="a@fife.com"),
                 card("c", name="Someone Else", email="x@other.com")]
        groups = detect.find_exact_duplicate_groups(cards)
        assert len(groups) == 1
        assert {m["id"] for m in groups[0]["cards"]} == {"a", "b"}

    def test_squashed_name_identity(self):
        cards = [card("a", name="FIFECAPITAL", email=""),
                 card("b", name="Fife Capital", email="")]
        groups = detect.find_exact_duplicate_groups(cards)
        assert len(groups) == 1

    def test_shared_corporate_domain_is_not_identity(self):
        cards = [card("a", name="Allan Fife", email="allan@fife.com"),
                 card("b", name="Mary Fife", email="mary@fife.com")]
        assert detect.find_exact_duplicate_groups(cards) == []

    def test_archived_pages_ignored(self):
        cards = [card("a", name="Fife Capital"),
                 card("b", name="Fife Capital", archived=True)]
        assert detect.find_exact_duplicate_groups(cards) == []


class TestFuzzyPairs:
    def test_similar_names_pair_up_for_adjudication(self):
        cards = [card("a", db="companies", name="REVA Corporation", email=None),
                 card("b", db="companies", name="REVA Holdings", email=None)]
        pairs = detect.find_fuzzy_duplicate_pairs(cards)
        assert len(pairs) == 1 and pairs[0]["score"] >= 0.72

    def test_distinct_emails_block_pairing(self):
        cards = [card("a", name="Jon Smith", email="jon@alpha.com"),
                 card("b", name="John Smith", email="john@beta.com")]
        assert detect.find_fuzzy_duplicate_pairs(cards) == []

    def test_blocking_prevents_unrelated_comparisons(self):
        cards = [card("a", name="Quadrant Growth", email=None),
                 card("b", name="Zephyr Partners", email=None)]
        assert detect.find_fuzzy_duplicate_pairs(cards) == []

    def test_a_similar_company_name_missed_by_a_prefix_only_bucket_still_pairs(self):
        # Squashed 4-char prefixes ("then"/"nort") differ, so the old
        # prefix-only blocking would never have compared these — the
        # legal-name-normalised trigram bucket does.
        cards = [card("a", db="companies", name="The Northwind Group", email=None),
                 card("b", db="companies", name="Northwind Capital", email=None)]
        pairs = detect.find_fuzzy_duplicate_pairs(cards)
        assert len(pairs) == 1


class TestContactBlocking:
    """Contacts need surname + domain/employer corroboration to block, not
    a bare shared first name (or a full-name prefix, which is nearly the
    same thing for typical "First Last" names)."""

    def test_shared_first_name_alone_never_pairs(self):
        cards = [card("a", name="John Adams", email="john@alpha.com"),
                 card("b", name="John Baker", email="john@beta.com")]
        assert detect.find_fuzzy_duplicate_pairs(cards) == []

    def test_shared_surname_with_no_corroboration_does_not_pair(self):
        cards = [card("a", name="Jon Smith", email="jon@alpha.com"),
                 card("b", name="Jonathan Smith", email="jonathan@beta.com")]
        assert detect.find_fuzzy_duplicate_pairs(cards) == []

    def test_a_shared_domain_alone_does_not_override_distinct_emails(self):
        # Two contacts sharing a corporate domain necessarily have two
        # DIFFERENT addresses at it — the pre-existing "distinct
        # identifiers" rule (different non-empty emails => not a pair)
        # already excludes this regardless of the shared domain.
        cards = [card("a", name="Jon Smith", email="jon@acme.com"),
                 card("b", name="Jonathan Smith", email="jonathan@acme.com")]
        assert detect.find_fuzzy_duplicate_pairs(cards) == []

    def test_shared_surname_and_employer_relation_pairs_even_without_email(self):
        cards = [card("a", name="Jon Smith", email=None,
                      relations={"Employed By": ["co1"]}),
                 card("b", name="Jonathan Smith", email=None,
                      relations={"Employed By": ["co1"]})]
        pairs = detect.find_fuzzy_duplicate_pairs(cards)
        assert len(pairs) == 1


class TestFundBlocking:
    """Explicit different vintages (Fund I vs Fund II) block a pair unless a
    shared manager corroborates it's the same fund entered twice."""

    def test_different_vintages_do_not_pair(self):
        cards = [card("a", db="funds", name="Piting Capital Fund I", email=None),
                 card("b", db="funds", name="Piting Capital Fund II", email=None)]
        assert detect.find_fuzzy_duplicate_pairs(cards) == []

    def test_different_vintages_with_a_shared_manager_still_pair(self):
        cards = [card("a", db="funds", name="Piting Capital Fund I", email=None,
                      relations={"Company": ["co1"]}),
                 card("b", db="funds", name="Piting Capital Fund II", email=None,
                      relations={"Company": ["co1"]})]
        pairs = detect.find_fuzzy_duplicate_pairs(cards)
        assert len(pairs) == 1

    def test_same_vintage_pairs_normally(self):
        cards = [card("a", db="funds", name="Piting Capital Fund I", email=None),
                 card("b", db="funds", name="Piting Capital Fund 1", email=None)]
        pairs = detect.find_fuzzy_duplicate_pairs(cards)
        assert len(pairs) == 1


class TestMutualNearest:
    """Each side of a surviving pair must consider the other among its own
    best few options — not merely someone above the review threshold."""

    @staticmethod
    def _pair(a_id, b_id, score):
        return {"a": {"id": a_id}, "b": {"id": b_id}, "score": score}

    def test_a_pair_outside_either_sides_top_k_is_dropped(self):
        pairs = sorted([
            self._pair("x", "a", 0.95),
            self._pair("x", "b", 0.90),
            self._pair("x", "c", 0.85),
            self._pair("x", "weak", 0.72),
        ], key=lambda p: -p["score"])
        out = detect._mutual_nearest(pairs, top_k=3)
        assert {(p["a"]["id"], p["b"]["id"]) for p in out} == \
            {("x", "a"), ("x", "b"), ("x", "c")}

    def test_a_pair_within_both_sides_top_k_survives(self):
        pairs = [self._pair("x", "y", 0.9)]
        assert detect._mutual_nearest(pairs, top_k=3) == pairs

    def test_one_sided_room_is_not_enough(self):
        # "y" has no other matches (trivially in its own top-k), but "x" has
        # three stronger matches elsewhere, pushing (x, y) out of x's top-3.
        pairs = sorted([
            self._pair("x", "y", 0.72),
            self._pair("x", "p", 0.95),
            self._pair("x", "q", 0.90),
            self._pair("x", "r", 0.85),
        ], key=lambda p: -p["score"])
        out = detect._mutual_nearest(pairs, top_k=3)
        ids = {(p["a"]["id"], p["b"]["id"]) for p in out}
        assert ("x", "y") not in ids
        assert len(ids) == 3


class TestSurvivorAndTransfers:
    def test_survivor_prefers_relations_then_fill(self):
        rich = card("a", name="Fife Capital", relations={"Notes": ["n1", "n2"]})
        poor = card("b", name="FIFECAPITAL")
        survivor, losers = detect.choose_survivor([poor, rich])
        assert survivor["id"] == "a" and losers[0]["id"] == "b"

    def test_transfer_plan_fills_unions_and_flags_conflicts(self):
        s = card("a", name="Fife Capital", extra_props={
            "Description": {"type": "rich_text", "rich_text": []},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "PE"}]},
        })
        l = card("b", name="FIFECAPITAL", email="x@fife.com", extra_props={
            "Description": {"type": "rich_text",
                            "rich_text": [{"plain_text": "Sydney manager"}]},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "RE"}]},
        })
        plan = detect.plan_merge_transfers(s, l)
        by_prop = {t["property"]: t for t in plan["transfers"]}
        assert by_prop["Description"]["kind"] == "fill"
        assert sorted(by_prop["Tags"]["value"]) == ["PE", "RE"]
        assert plan["conflicts"] == []
        # Loser's title is never transferred.
        assert "Name" not in by_prop

    def test_conflicting_values_not_overwritten(self):
        s = card("a", name="Fife", extra_props={
            "City": {"type": "rich_text", "rich_text": [{"plain_text": "Sydney"}]}})
        l = card("b", name="Fife2", extra_props={
            "City": {"type": "rich_text", "rich_text": [{"plain_text": "Melbourne"}]}})
        plan = detect.plan_merge_transfers(s, l)
        assert plan["transfers"] == []
        assert plan["conflicts"][0]["property"] == "City"


class TestOtherIssues:
    def test_missing_props_respect_live_schema(self):
        c = card("a", name="X", extra_props={
            "Type": {"type": "select", "select": None}})
        found = detect.find_missing_props([c], "contacts", {"Type"})
        assert found[0]["missing"] == ["Type"]
        assert detect.find_missing_props([c], "contacts", {"Renamed"}) == []

    def test_dangling_relations_only_against_complete_scans(self):
        c = card("a", name="X", relations={"Employed By": ["co1", "gone"]})
        rel_map = {("contacts", "Employed By"): "companies-db"}
        found = detect.find_dangling_relations(
            [c], rel_map, {"companies-db": {"co1"}})
        assert found[0]["dangling"] == ["gone"] and found[0]["keep"] == ["co1"]
        # Target DB not scanned → out of scope, nothing flagged.
        assert detect.find_dangling_relations([c], rel_map, {}) == []

    def test_formatting_whitespace_and_email_case_only(self):
        c = card("a", name="  Fife   Capital ", email="Allan@Fife.COM")
        kinds = {f["kind"]: f for f in detect.find_formatting_issues([c])}
        assert kinds["title_whitespace"]["to"] == "Fife Capital"
        assert kinds["email_case"]["to"] == "allan@fife.com"
        clean = card("b", name="Priya Patel", email="x@acme.com")
        assert detect.find_formatting_issues([clean]) == []

    def test_person_name_gets_proper_capitalisation(self):
        # "Kristoffer JONSSON" — the surname should be proper-cased too.
        c = card("a", name="Kristoffer JONSSON ")
        found = detect.find_formatting_issues([c])
        assert found[0]["kind"] == "name_case"
        assert found[0]["to"] == "Kristoffer Jonsson"
        low = card("b", name="alex ochoa")
        assert detect.find_formatting_issues([low])[0]["to"] == "Alex Ochoa"

    def test_name_case_preserves_credentials_and_particles(self):
        keep = card("a", name="Alex Ochoa, CAIA")
        assert detect.find_formatting_issues([keep]) == []
        particle = card("b", name="Robert van Beek")
        assert detect.find_formatting_issues([particle]) == []
        hyphen = card("c", name="JEAN-PAUL O'BRIEN")
        assert detect.find_formatting_issues([hyphen])[0]["to"] == "Jean-Paul O'Brien"

    def test_company_names_never_recased(self):
        # Acronym-hazardous: KKR, REVA etc. stay exactly as typed.
        c = card("a", db="companies", name="REVA HOLDINGS", email=None)
        assert detect.find_formatting_issues([c]) == []

    def test_email_with_clutter_extracts_the_bare_address(self):
        c = card("a", name="Roy Carmo",
                 email="C- 5165874019 W- 6466883375 roy@carmocompanies.com")
        found = detect.find_formatting_issues([c])
        assert found[0]["kind"] == "email_extract"
        assert found[0]["to"] == "roy@carmocompanies.com"
        assert "5165874019" in found[0]["junk"]

    def test_email_with_display_name_extracts_too(self):
        c = card("a", name="Allison Stavro",
                 email="Allison Stavro <allison@sinefine.co>")
        found = detect.find_formatting_issues([c])
        assert found[0]["kind"] == "email_extract"
        assert found[0]["to"] == "allison@sinefine.co"

    def test_email_with_several_addresses_left_alone(self):
        # Choosing between two different addresses would be a guess.
        c = card("a", name="Two Mails",
                 email="a@one.com or b@two.com")
        assert detect.find_formatting_issues([c]) == []

    def test_employer_inference_exact_domain_only(self):
        co = card("co1", db="companies", name="Fife Capital", email=None,
                  extra_props={"Website": {"type": "url",
                                           "url": "https://www.fife.com"}})
        linked = card("a", name="Has Employer", email="x@fife.com",
                      relations={"Employed By": ["coX"]})
        match = card("b", name="Allan", email="allan@fife.com")
        generic = card("c", name="Gmail Person", email="p@gmail.com")
        unknown = card("d", name="Stranger", email="s@nowhere.io")
        out = detect.infer_employers([linked, match, generic, unknown], [co])
        assert [l["contact"]["id"] for l in out["links"]] == ["b"]
        assert [c["contact"]["id"] for c in out["company_candidates"]] == ["d"]
