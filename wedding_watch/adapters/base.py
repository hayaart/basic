"""어댑터 공통 인터페이스."""

from __future__ import annotations

import abc
from typing import Any

from ..models import Slot


class FetchError(RuntimeError):
    """빈자리 조회 실패."""


class LoginRequired(FetchError):
    """로그인 세션이 만료됨. 저장된 쿠키를 갱신해야 한다."""


class Adapter(abc.ABC):
    """월 단위로 예약 가능 슬롯을 가져온다."""

    @abc.abstractmethod
    def fetch_month(self, year: int, month: int) -> list[Slot]:
        """해당 연·월의 예약 가능 슬롯 목록."""

    def close(self) -> None:
        """자원 정리. 기본은 아무것도 하지 않는다."""


def template_vars(hall_code: str, year: int, month: int) -> dict[str, str]:
    """설정 문자열에 끼워 넣을 수 있는 변수들."""
    return {
        "hall_code": hall_code,
        "year": f"{year:04d}",
        "month": f"{month:02d}",
        "month_no_pad": str(month),
        "ym": f"{year:04d}{month:02d}",
        "year_month": f"{year:04d}-{month:02d}",
    }


def render(value: Any, variables: dict[str, str]) -> Any:
    """문자열/리스트/딕셔너리 안의 {hall_code} 같은 자리표시자를 채운다."""
    if isinstance(value, str):
        try:
            return value.format(**variables)
        except (KeyError, IndexError) as exc:
            raise FetchError(
                f"설정 문자열의 자리표시자를 채울 수 없습니다: {value!r} ({exc})"
            ) from exc
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    return value
