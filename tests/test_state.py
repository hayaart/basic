from wedding_watch.models import Slot
from wedding_watch.state import SeenState


def test_diff_reports_new_then_nothing(tmp_path):
    state = SeenState(tmp_path / "seen.json")
    slots = [Slot("2027-05-08"), Slot("2027-05-15")]

    new, gone = state.diff(slots)
    assert {s.key for s in new} == {"2027-05-08|", "2027-05-15|"}
    assert gone == []

    state.commit(slots)
    new, gone = state.diff(slots)
    assert new == [] and gone == []


def test_disappeared_slot_is_forgotten_and_realerts(tmp_path):
    state = SeenState(tmp_path / "seen.json")
    state.commit([Slot("2027-05-08")])

    new, gone = state.diff([])
    assert [s.key for s in gone] == ["2027-05-08|"]
    state.commit([])
    assert state.seen == {}

    # 다시 나타나면 새 빈자리로 취급해 또 알린다.
    new, _ = state.diff([Slot("2027-05-08")])
    assert [s.key for s in new] == ["2027-05-08|"]


def test_state_survives_restart(tmp_path):
    path = tmp_path / "seen.json"
    first = SeenState(path)
    first.commit([Slot("2027-09-04", "11:00")])
    first.save()

    second = SeenState(path)
    assert list(second.seen) == ["2027-09-04|11:00"]
    assert second.diff([Slot("2027-09-04", "11:00")]) == ([], [])


def test_corrupt_state_file_starts_clean(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert SeenState(path).seen == {}


def test_failure_counter(tmp_path):
    state = SeenState(tmp_path / "seen.json")
    assert state.record_failure("boom") == 1
    assert state.record_failure("boom") == 2
    state.record_success()
    assert state.meta["consecutive_failures"] == 0
