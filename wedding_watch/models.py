"""도메인 모델."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_DIGITS = re.compile(r"\d+")

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def normalize_date(value: object, date_format: str | None = None) -> str:
    """여러 형태의 날짜 표현을 YYYY-MM-DD 로 통일한다."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        raise ValueError("빈 날짜 값")
    if date_format:
        return dt.datetime.strptime(text, date_format).date().isoformat()
    digits = "".join(_DIGITS.findall(text))
    if len(digits) >= 8:
        digits = digits[:8]
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    raise ValueError(f"날짜를 해석할 수 없습니다: {value!r}")


@dataclass(frozen=True)
class Slot:
    """예약 가능한 예식 슬롯 하나."""

    date: str  # YYYY-MM-DD
    time: str = ""  # "12:30" 등. 시간 구분이 없으면 빈 문자열.
    label: str = ""  # 사이트가 준 부가 설명(홀 이름, 잔여 수 등).

    @property
    def key(self) -> str:
        return f"{self.date}|{self.time}"

    @property
    def as_date(self) -> dt.date:
        return dt.date.fromisoformat(self.date)

    @property
    def month(self) -> str:
        return self.date[:7]

    def human(self) -> str:
        weekday = WEEKDAY_KO[self.as_date.weekday()]
        text = f"{self.date}({weekday})"
        if self.time:
            text += f" {self.time}"
        if self.label:
            text += f" · {self.label}"
        return text

    @classmethod
    def from_key(cls, key: str) -> "Slot":
        date, _, time = key.partition("|")
        return cls(date=date, time=time)


def sort_slots(slots: list[Slot]) -> list[Slot]:
    return sorted(slots, key=lambda s: (s.date, s.time))
