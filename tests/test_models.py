import pytest

from wedding_watch.models import Slot, normalize_date, sort_slots


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("20270508", "2027-05-08"),
        ("2027-05-08", "2027-05-08"),
        ("2027.05.08", "2027-05-08"),
        ("2027/05/08 11:00", "2027-05-08"),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_date_with_format():
    assert normalize_date("08/05/2027", "%d/%m/%Y") == "2027-05-08"


def test_normalize_date_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_date("다음주")


def test_slot_key_and_human():
    slot = Slot(date="2027-05-08", time="12:30", label="A홀")
    assert slot.key == "2027-05-08|12:30"
    assert slot.human() == "2027-05-08(토) 12:30 · A홀"
    assert Slot.from_key(slot.key) == Slot(date="2027-05-08", time="12:30")


def test_sort_slots():
    slots = [Slot("2027-06-01"), Slot("2027-05-08", "14:00"), Slot("2027-05-08", "11:00")]
    assert [s.key for s in sort_slots(slots)] == [
        "2027-05-08|11:00",
        "2027-05-08|14:00",
        "2027-06-01|",
    ]
