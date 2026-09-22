"""이미 알린 슬롯을 기억해서 중복 알림을 막는다."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path

from .models import Slot


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class SeenState:
    """디스크에 저장되는 관찰 상태.

    seen: 슬롯 키 -> {first_seen, last_seen, label}
    meta: 연속 실패 횟수 등 운영 정보.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.seen: dict[str, dict] = {}
        self.meta: dict = {"consecutive_failures": 0, "failure_alerted": False}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 상태 파일이 깨졌으면 처음부터 시작한다. 최악의 경우 알림이 한 번 더 갈 뿐이다.
            return
        self.seen = data.get("seen", {}) or {}
        meta = data.get("meta") or {}
        self.meta.update(meta)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seen": self.seen, "meta": self.meta, "saved_at": _now()}
        # 같은 디렉터리에 임시 파일을 쓰고 교체해서 중간에 죽어도 파일이 깨지지 않게 한다.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".seen-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def diff(self, slots: list[Slot]) -> tuple[list[Slot], list[Slot]]:
        """이번에 새로 생긴 슬롯과 사라진 슬롯을 돌려준다."""
        current = {slot.key: slot for slot in slots}
        new = [slot for key, slot in current.items() if key not in self.seen]
        gone = [Slot.from_key(key) for key in self.seen if key not in current]
        return new, gone

    def commit(self, slots: list[Slot]) -> None:
        """현재 관찰 결과를 반영한다. 사라진 슬롯은 기억에서 지운다."""
        now = _now()
        current = {slot.key: slot for slot in slots}
        for key, slot in current.items():
            entry = self.seen.get(key)
            if entry is None:
                self.seen[key] = {"first_seen": now, "last_seen": now, "label": slot.label}
            else:
                entry["last_seen"] = now
                entry["label"] = slot.label
        for key in list(self.seen):
            if key not in current:
                # 다시 나타나면 새 빈자리로 취급해 다시 알린다.
                del self.seen[key]

    def record_success(self) -> None:
        self.meta["consecutive_failures"] = 0
        self.meta["failure_alerted"] = False
        self.meta["last_success"] = _now()

    def record_failure(self, message: str) -> int:
        self.meta["consecutive_failures"] = int(self.meta.get("consecutive_failures", 0)) + 1
        self.meta["last_failure"] = _now()
        self.meta["last_error"] = message[:500]
        return self.meta["consecutive_failures"]
