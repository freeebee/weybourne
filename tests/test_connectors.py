"""Connector behaviour: free-slot computation and snapshot parsing (offline)."""
import datetime as dt
import json

from src.connectors.graph import (
    GraphConnector,
    _compute_free_slots,
    _email_from_snapshot,
    _event_from_snapshot,
    _load_snapshot,
)
from src.connectors.notion_client import NotionConnector, sleeve_page_id


class TestFreeSlots:
    MONDAY_9AM = dt.datetime(2026, 8, 3, 9, 0)

    def _slots(self, busy=None, **kwargs):
        params = dict(
            now=self.MONDAY_9AM, days_ahead=2, slot_minutes=30,
            work_start_hour=9, work_end_hour=17, max_slots=5,
            busy_intervals=busy or [],
        )
        params.update(kwargs)
        return _compute_free_slots(**params)

    def test_returns_requested_number_of_slots(self):
        assert len(self._slots()) == 5

    def test_slots_are_the_right_length(self):
        slot = self._slots()[0]
        start = dt.datetime.fromisoformat(slot.start)
        end = dt.datetime.fromisoformat(slot.end)
        assert (end - start).total_seconds() == 30 * 60

    def test_busy_periods_are_excluded(self):
        busy = [(dt.datetime(2026, 8, 3, 9, 0), dt.datetime(2026, 8, 3, 11, 0))]
        starts = [s.start for s in self._slots(busy=busy)]
        assert not any("2026-08-03T09" in s or "2026-08-03T10" in s for s in starts)
        assert starts[0] == "2026-08-03T11:00:00"

    def test_partially_overlapping_meeting_blocks_the_slot(self):
        # A meeting from 09:15-09:45 makes both the 09:00 and 09:30 slots unusable.
        busy = [(dt.datetime(2026, 8, 3, 9, 15), dt.datetime(2026, 8, 3, 9, 45))]
        assert self._slots(busy=busy)[0].start == "2026-08-03T10:00:00"

    def test_never_offers_a_slot_in_the_past(self):
        afternoon = dt.datetime(2026, 8, 3, 14, 20)
        first = self._slots(now=afternoon)[0]
        assert dt.datetime.fromisoformat(first.start) >= afternoon

    def test_skips_weekends(self):
        friday_4pm = dt.datetime(2026, 8, 7, 16, 0)
        for slot in self._slots(now=friday_4pm, days_ahead=3):
            assert dt.datetime.fromisoformat(slot.start).weekday() < 5

    def test_stays_within_working_hours(self):
        for slot in self._slots(max_slots=30):
            start = dt.datetime.fromisoformat(slot.start)
            end = dt.datetime.fromisoformat(slot.end)
            assert start.hour >= 9 and end.hour <= 17

    def test_slot_label_is_human_readable(self):
        label = self._slots()[0].label()
        assert "Mon" in label and "09:00" in label

    def test_lead_time_prevents_offering_an_imminent_slot(self):
        # Offering a call starting in ten minutes is worse than offering nothing.
        graph = GraphConnector()
        soonest = graph.find_free_slots(max_slots=1)[0]
        immediate = graph.find_free_slots(max_slots=1, min_lead_hours=0)[0]
        assert soonest.start > immediate.start


class TestSnapshotParsing:
    def test_parses_flat_email_shape(self):
        email = _email_from_snapshot({
            "id": "1", "subject": "Fund VII", "sender_name": "Katie",
            "sender_email": "k@cendana.com", "received": "2026-07-30T08:12:00",
            "body": "Full body", "has_attachments": True,
        })
        assert email.sender_email == "k@cendana.com"
        assert email.has_attachments

    def test_parses_raw_graph_email_shape(self):
        email = _email_from_snapshot({
            "id": "2", "subject": "LP letter",
            "from": {"emailAddress": {"name": "Catherine", "address": "c@piting.com"}},
            "receivedDateTime": "2026-07-29T15:40:00",
            "body": {"contentType": "text", "content": "Body text"},
        })
        assert email.sender_name == "Catherine"
        assert email.sender_email == "c@piting.com"

    def test_strips_html_from_graph_bodies(self):
        email = _email_from_snapshot({
            "id": "3", "from": {"emailAddress": {"address": "a@b.com"}},
            "receivedDateTime": "2026-07-29T00:00:00",
            "body": {"contentType": "html", "content": "<p>Hello <b>there</b></p>"},
        })
        assert "<p>" not in email.body
        assert "Hello" in email.body

    def test_parses_flat_event_shape(self):
        event = _event_from_snapshot({
            "id": "e1", "subject": "GP meeting", "start": "2026-08-04T10:00:00",
            "end": "2026-08-04T11:00:00",
            "attendees": [{"name": "Old Well", "email": "ir@oldwell.com"}],
        })
        assert event.attendees[0].email == "ir@oldwell.com"

    def test_parses_raw_graph_event_shape(self):
        event = _event_from_snapshot({
            "id": "e2", "subject": "Call",
            "start": {"dateTime": "2026-08-05T16:00:00"},
            "end": {"dateTime": "2026-08-05T16:30:00"},
            "attendees": [{"emailAddress": {"name": "J A", "address": "j@irvine.org"}}],
        })
        assert event.start == "2026-08-05T16:00:00"
        assert event.attendees[0].name == "J A"

    def test_missing_snapshot_returns_none(self, tmp_path):
        assert _load_snapshot(tmp_path / "nope.json") is None

    def test_malformed_snapshot_returns_none_rather_than_raising(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        assert _load_snapshot(path) is None

    def test_accepts_graph_value_wrapper(self, tmp_path):
        path = tmp_path / "wrapped.json"
        path.write_text(json.dumps({"value": [{"id": "1"}, {"id": "2"}]}))
        assert len(_load_snapshot(path)) == 2


class TestMockMode:
    def test_graph_serves_sample_data_without_credentials(self):
        graph = GraphConnector()
        assert not graph.live
        assert len(graph.list_inbox()) > 0

    def test_notion_serves_sample_records_without_a_token(self):
        notion = NotionConnector()
        assert not notion.live
        assert notion.list_contacts() and notion.list_companies() and notion.list_funds()

    def test_draft_creation_is_a_no_op_in_mock_mode(self):
        result = GraphConnector().create_reply_draft("mock-1", "Body")
        assert result["status"] == "mock-created"

    def test_page_creation_is_a_no_op_in_mock_mode(self):
        result = NotionConnector().create_page("db", {"Name": "x"})
        assert result["mock"] is True


def test_sleeve_page_ids_resolve_for_each_sleeve():
    assert sleeve_page_id("Private Growth")
    assert sleeve_page_id("Public Growth")
    assert sleeve_page_id("Diversifiers")
    assert sleeve_page_id("Unclear") is None
