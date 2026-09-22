import pytest

from wedding_watch.adapters.base import Adapter, FetchError, LoginRequired
from wedding_watch.config import Config, NtfyConfig, PollConfig, TargetConfig
from wedding_watch.models import Slot
from wedding_watch.state import SeenState
from wedding_watch.watcher import Watcher, filter_slots


class FakeAdapter(Adapter):
    """월 -> 슬롯 목록. 값 대신 예외를 넣으면 그 월 조회가 실패한다."""

    def __init__(self, by_month):
        self.by_month = by_month
        self.calls = []

    def fetch_month(self, year, month):
        self.calls.append((year, month))
        result = self.by_month.get(f"{year:04d}-{month:02d}", [])
        if isinstance(result, Exception):
            raise result
        return result


class FakeNotifier:
    def __init__(self):
        self.new = []
        self.gone = []
        self.failures = []
        self.recovered = 0

    def notify_new_slots(self, slots, hall_name, click_url=None):
        self.new.append(list(slots))
        return True

    def notify_gone_slots(self, slots, hall_name):
        self.gone.append(list(slots))
        return True

    def notify_failure(self, message, failures):
        self.failures.append((message, failures))
        return True

    def notify_recovered(self):
        self.recovered += 1
        return True

    def notify_heartbeat(self, hall_name, count):
        return True


@pytest.fixture
def config(tmp_path):
    return Config(
        target=TargetConfig(
            hall_code="5",
            hall_name="삼성금융연수원",
            months=["2027-05", "2027-06", "2027-09", "2027-10", "2027-11"],
        ),
        poll=PollConfig(interval_seconds=600, failure_alert_after=2),
        ntfy=NtfyConfig(topic="t"),
        state_file=str(tmp_path / "seen.json"),
    )


def make_watcher(config, by_month):
    notifier = FakeNotifier()
    watcher = Watcher(
        config,
        adapter=FakeAdapter(by_month),
        notifier=notifier,
        state=SeenState(config.state_file),
    )
    return watcher, notifier


def test_filter_drops_other_months_and_dedupes(config):
    slots = [
        Slot("2027-05-08"),
        Slot("2027-05-08"),      # 중복
        Slot("2027-07-10"),      # 대상 월 아님
        Slot("2027-11-20"),
    ]
    assert [s.key for s in filter_slots(slots, config)] == ["2027-05-08|", "2027-11-20|"]


def test_filter_respects_weekday_and_exclusions(config):
    config.target.weekdays = [5, 6]          # 토, 일만
    config.target.exclude_dates = ["2027-05-15"]
    slots = [Slot("2027-05-08"), Slot("2027-05-15"), Slot("2027-05-11")]  # 토, 토, 화
    assert [s.key for s in filter_slots(slots, config)] == ["2027-05-08|"]


def test_checks_every_target_month(config):
    watcher, _ = make_watcher(config, {})
    watcher.check_once()
    assert watcher.adapter.calls == [(2027, 5), (2027, 6), (2027, 9), (2027, 10), (2027, 11)]


def test_notifies_once_per_slot(config):
    watcher, notifier = make_watcher(config, {"2027-05": [Slot("2027-05-08", "11:00")]})

    watcher.run_once()
    assert [s.key for s in notifier.new[0]] == ["2027-05-08|11:00"]

    watcher.run_once()   # 같은 빈자리 -> 다시 알리지 않는다
    assert len(notifier.new) == 1


def test_notifies_only_the_newly_added_slot(config):
    by_month = {"2027-05": [Slot("2027-05-08")]}
    watcher, notifier = make_watcher(config, by_month)
    watcher.run_once()

    by_month["2027-05"] = [Slot("2027-05-08"), Slot("2027-05-22")]
    watcher.run_once()
    assert [s.key for s in notifier.new[1]] == ["2027-05-22|"]


def test_disappearance_is_silent_by_default_and_reannounced_on_return(config):
    by_month = {"2027-06": [Slot("2027-06-05")]}
    watcher, notifier = make_watcher(config, by_month)
    watcher.run_once()

    by_month["2027-06"] = []
    watcher.run_once()
    assert notifier.gone == []

    by_month["2027-06"] = [Slot("2027-06-05")]
    watcher.run_once()
    assert len(notifier.new) == 2


def test_disappearance_notified_when_enabled(config):
    config.poll.notify_on_disappear = True
    by_month = {"2027-06": [Slot("2027-06-05")]}
    watcher, notifier = make_watcher(config, by_month)
    watcher.run_once()
    by_month["2027-06"] = []
    watcher.run_once()
    assert [s.key for s in notifier.gone[0]] == ["2027-06-05|"]


def test_one_failing_month_does_not_block_the_others(config):
    watcher, notifier = make_watcher(
        config,
        {"2027-05": FetchError("타임아웃"), "2027-09": [Slot("2027-09-04")]},
    )
    result = watcher.run_once()
    assert [s.key for s in result.slots] == ["2027-09-04|"]
    assert result.errors and "2027-05" in result.errors[0]
    assert [s.key for s in notifier.new[0]] == ["2027-09-04|"]


def test_all_months_failing_raises_and_alerts_after_threshold(config):
    watcher, notifier = make_watcher(config, {m: FetchError("끊김") for m in config.target.months})

    assert watcher.run_once() is None
    assert notifier.failures == []          # 1회 실패로는 알리지 않는다

    assert watcher.run_once() is None
    assert notifier.failures[0][1] == 2     # 2회 연속에서 알림

    watcher.run_once()
    assert len(notifier.failures) == 1      # 계속 실패해도 알림은 한 번만


def test_recovery_is_announced(config):
    by_month = {m: FetchError("끊김") for m in config.target.months}
    watcher, notifier = make_watcher(config, by_month)
    watcher.run_once()
    watcher.run_once()
    assert notifier.failures

    for month in config.target.months:
        by_month[month] = []
    watcher.run_once()
    assert notifier.recovered == 1


def test_login_expiry_is_reported_as_failure(config):
    watcher, notifier = make_watcher(config, {"2027-05": LoginRequired("세션 만료")})
    assert watcher.run_once() is None
    assert watcher.state.meta["consecutive_failures"] == 1
    assert "세션 만료" in watcher.state.meta["last_error"]


def test_sleep_stays_within_jitter(config):
    config.poll.jitter_seconds = 60
    watcher, _ = make_watcher(config, {})
    for _ in range(50):
        assert 540 <= watcher.sleep_seconds() <= 660
