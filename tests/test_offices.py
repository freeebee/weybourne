"""The canonical multi-office Address format: written by Felix's office
research, read back by the travel planner."""
from src.features.offices import format_office_lines, office_for_city, parse_office_lines


LINES = ("London, UK — 25 Old Broad Street, EC2N 1HQ\n"
         "Sydney, Australia — Level 15, 1 Macquarie Place, NSW 2000")


def test_format_and_parse_round_trip():
    offices = [
        {"city": "London", "country": "UK",
         "address": "25 Old Broad Street, EC2N 1HQ"},
        {"city": "Sydney", "country": "Australia",
         "address": "Level 15, 1 Macquarie Place, NSW 2000"},
    ]
    assert format_office_lines(offices) == LINES
    assert parse_office_lines(LINES) == offices


def test_officeless_entries_are_dropped_and_placeless_ones_still_format():
    assert format_office_lines([{"city": "Oslo", "country": "", "address": ""},
                                {"city": "", "country": "",
                                 "address": "1 Some Street"}]) == "1 Some Street"


def test_legacy_freeform_addresses_survive_parsing():
    parsed = parse_office_lines("Floor 2, 10 Anson Road, Singapore 079903")
    assert parsed == [{"city": "", "country": "",
                       "address": "Floor 2, 10 Anson Road, Singapore 079903"}]


def test_office_for_city_picks_the_visited_city():
    assert office_for_city(LINES, "sydney") == "Level 15, 1 Macquarie Place, NSW 2000"
    # No office in the visited city: no hint, never a wrong-city address.
    assert office_for_city(LINES, "Tokyo") == ""


def test_office_for_city_returns_a_single_freeform_record_as_is():
    assert office_for_city("10 Anson Road, Singapore", "Sydney") \
        == "10 Anson Road, Singapore"
    assert office_for_city("", "Sydney") == ""
