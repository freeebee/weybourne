"""One complete demo-mode travel workflow through the public HTTP contract."""
from fastapi.testclient import TestClient

import api.main as api
from src.features.travel.store import TravelStore


def test_travel_api_demo_journey(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_travel_store", TravelStore(tmp_path / "travel.db"))
    client = TestClient(api.app)

    options = client.get("/api/travel/options").json()
    # The journey drafts and sends outreach, so it needs a person with an
    # email — manager rows (no person, no address) may lead the list.
    person = next(c for c in options["candidates"] if c["email"])
    created = client.post("/api/travel/trips", json={
        "name": "Demo trip",
        "anchor": {"type": "manager", "id": person["company_id"],
                   "label": person["company"]},
        "start_date": "2026-09-07", "end_date": "2026-09-11",
        "candidate_ids": [person["id"]],
        "settings": {"nightly_budget_gbp": 250},
    })
    assert created.status_code == 200, created.text
    trip = created.json()

    resolved = client.post(f"/api/travel/trips/{trip['id']}/locations/resolve")
    assert resolved.status_code == 200
    confirmed = client.post(f"/api/travel/trips/{trip['id']}/locations/confirm", json={
        "candidate_id": person["id"], "choice_index": 0,
    })
    assert confirmed.status_code == 200

    city_id = confirmed.json()["cities"][0]["id"]
    hotels = client.post(f"/api/travel/trips/{trip['id']}/hotels/search",
                         json={"city_id": city_id})
    assert hotels.status_code == 200 and hotels.json()["within_budget"]
    selected = client.post(f"/api/travel/trips/{trip['id']}/hotels/select",
                           json={"hotel_id": hotels.json()["hotels"][0]["id"]})
    assert selected.status_code == 200

    optimized = client.post(f"/api/travel/trips/{trip['id']}/optimize")
    assert optimized.status_code == 200
    assert len(optimized.json()["candidates"][0]["slots"]) >= 2

    drafted = client.post(f"/api/travel/trips/{trip['id']}/outreach/draft",
                          json={"tier": 1})
    assert drafted.status_code == 200 and len(drafted.json()["messages"]) == 1
    sent = client.post(f"/api/travel/trips/{trip['id']}/outreach/send",
                       json={"tier": 1, "demo": True})
    assert sent.status_code == 200 and sent.json()["messages"][0]["state"] == "sent"

    repeated = client.post(f"/api/travel/trips/{trip['id']}/outreach/send",
                           json={"tier": 1, "demo": True})
    assert repeated.status_code == 200
    assert len(api._travel_store.actions(trip["id"])) == 1
