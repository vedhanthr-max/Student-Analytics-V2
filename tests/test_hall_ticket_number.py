from app.legacy import hall_ticket_number


def test_hall_ticket_number_with_year_prefix():
    assert hall_ticket_number("2026CSE001", year=2027) == "HT2026CSE001"


def test_hall_ticket_number_without_year_prefix():
    assert hall_ticket_number("1", year=2027) == "HT20271"
