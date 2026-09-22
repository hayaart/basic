"""감시 루프: 주기적으로 조회 → 새 빈자리만 골라 ntfy 로 알림."""

from __future__ import annotations

import datetime as dt
import logging
import random
import signal
import time
from dataclasses import dataclass

from .adapters import Adapter, FetchError, LoginRequired, build_adapter
from .config import Config
from .models import Slot, sort_slots
from .notify import Notifier
from .state import SeenState

log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    slots: list[Slot]
    new: list[Slot]
    gone: list[Slot]
    errors: list[str]


def parse_month(month: str) -> tuple[int, int]:
    year, _, mon = month.partition("-")
    return int(year), int(mon)


def filter_slots(slots: list[Slot], config: Config) -> list[Slot]:
    """대상 월/요일/제외일 조건에 맞는 슬롯만 남기고 중복을 제거한다."""
    months = set(config.target.months)
    weekdays = set(config.target.weekdays)
    excluded = set(config.target.exclude_dates)
    kept: dict[str, Slot] = {}
    for slot in slots:
        if slot.month not in months:
            continue
        if slot.date in excluded:
            continue
        if weekdays and slot.as_date.weekday() not in weekdays:
            continue
        kept.setdefault(slot.key, slot)
    return sort_slots(list(kept.values()))


class Watcher:
    def __init__(
        self,
        config: Config,
        adapter: Adapter | None = None,
        notifier: Notifier | None = None,
        state: SeenState | None = None,
    ):
        self.config = config
        self.adapter = adapter or build_adapter(config)
        self.notifier = notifier or Notifier(config.ntfy, timeout=config.poll.timeout_seconds)
        self.state = state or SeenState(config.state_file)
        self._stop = False
        self._last_heartbeat = time.monotonic()

    # --- 한 번 확인하기 ------------------------------------------------
    def check_once(self) -> CheckResult:
        """모든 대상 월을 조회한다. 일부 월이 실패해도 나머지는 진행한다."""
        collected: list[Slot] = []
        errors: list[str] = []
        for month in self.config.target.months:
            year, mon = parse_month(month)
            try:
                found = self.adapter.fetch_month(year, mon)
            except LoginRequired:
                raise
            except FetchError as exc:
                log.warning("%s 조회 실패: %s", month, exc)
                errors.append(f"{month}: {exc}")
                continue
            log.info("%s 조회 완료: 원본 %d건", month, len(found))
            collected.extend(found)

        if errors and not collected:
            raise FetchError("; ".join(errors))

        slots = filter_slots(collected, self.config)
        new, gone = self.state.diff(slots)
        return CheckResult(slots=slots, new=new, gone=gone, errors=errors)

    def run_once(self) -> CheckResult | None:
        """한 사이클: 조회 → 알림 → 상태 저장. 실패하면 None."""
        try:
            result = self.check_once()
        except (FetchError, LoginRequired) as exc:
            self._handle_failure(exc)
            return None

        if result.new:
            log.info("새 빈자리 %d건: %s", len(result.new), [s.key for s in result.new])
            self.notifier.notify_new_slots(
                result.new, self.config.target.hall_name, self.config.ntfy.click_url
            )
        if result.gone and self.config.poll.notify_on_disappear:
            self.notifier.notify_gone_slots(result.gone, self.config.target.hall_name)

        was_failing = int(self.state.meta.get("consecutive_failures", 0)) > 0
        alerted = bool(self.state.meta.get("failure_alerted"))
        self.state.commit(result.slots)
        self.state.record_success()
        if was_failing and alerted:
            self.notifier.notify_recovered()
        self._maybe_heartbeat(len(result.slots))
        self.state.save()
        return result

    def _handle_failure(self, exc: Exception) -> None:
        message = str(exc)
        failures = self.state.record_failure(message)
        log.error("확인 실패 (%d회 연속): %s", failures, message)
        threshold = self.config.poll.failure_alert_after
        if threshold and failures >= threshold and not self.state.meta.get("failure_alerted"):
            if self.notifier.notify_failure(message, failures):
                self.state.meta["failure_alerted"] = True
        self.state.save()

    def _maybe_heartbeat(self, slot_count: int) -> None:
        hours = self.config.poll.heartbeat_hours
        if not hours:
            return
        if time.monotonic() - self._last_heartbeat < hours * 3600:
            return
        self._last_heartbeat = time.monotonic()
        self.notifier.notify_heartbeat(self.config.target.hall_name, slot_count)

    # --- 계속 돌기 ------------------------------------------------------
    def request_stop(self, *_args) -> None:
        log.info("종료 신호를 받았습니다. 현재 사이클을 마치고 종료합니다.")
        self._stop = True

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self.request_stop)
            except (ValueError, OSError):  # pragma: no cover - 메인 스레드가 아닐 때
                pass

    def sleep_seconds(self) -> float:
        jitter = self.config.poll.jitter_seconds
        offset = random.uniform(-jitter, jitter) if jitter else 0.0
        return max(30.0, self.config.poll.interval_seconds + offset)

    def run_forever(self) -> int:
        self.install_signal_handlers()
        interval = self.config.poll.interval_seconds
        log.info(
            "감시 시작: %s (홀 코드 %s), 대상 %s, %d초 간격",
            self.config.target.hall_name,
            self.config.target.hall_code,
            ", ".join(self.config.target.months),
            interval,
        )
        try:
            while not self._stop:
                started = time.monotonic()
                self.run_once()
                if self._stop:
                    break
                delay = self.sleep_seconds() - (time.monotonic() - started)
                self._interruptible_sleep(max(delay, 1.0))
        finally:
            self.adapter.close()
        log.info("감시를 종료했습니다.")
        return 0

    def _interruptible_sleep(self, seconds: float) -> None:
        """종료 신호에 빠르게 반응하도록 잘게 쪼개 잔다."""
        deadline = time.monotonic() + seconds
        next_run = dt.datetime.now() + dt.timedelta(seconds=seconds)
        log.info("다음 확인: %s", next_run.strftime("%H:%M:%S"))
        while not self._stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))
