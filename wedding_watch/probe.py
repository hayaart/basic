"""로그인이 정말 필요한지 실제로 확인한다.

'로그인이 필요하다'는 건 추측하지 말고 측정해야 한다. 저장된 쿠키를 모두 빼고
같은 요청을 보내서, 그래도 달력이 나오는지 본다.
"""

from __future__ import annotations

import dataclasses

from .adapters.api import ApiAdapter
from .adapters.base import FetchError, LoginRequired
from .config import Config
from .models import Slot
from .watcher import parse_month


@dataclasses.dataclass
class ProbeResult:
    login_required: bool
    detail: str
    slots: list[Slot] = dataclasses.field(default_factory=list)
    # 조회 자체가 실패했지만 로그인 때문인지 확실하지 않은 경우.
    inconclusive: bool = False

    def summary(self) -> str:
        if self.inconclusive:
            return f"판단 불가: {self.detail}"
        if self.login_required:
            return f"로그인이 필요합니다: {self.detail}"
        return f"로그인 없이도 조회됩니다: {self.detail}"


def probe_without_login(config: Config) -> ProbeResult:
    """쿠키·자동로그인을 모두 끄고 첫 대상 월을 조회해 본다."""
    if config.source.mode != "api":
        return ProbeResult(
            login_required=True,
            detail="browser 모드는 자동 판단을 지원하지 않습니다. 시크릿 창으로 직접 확인하세요.",
            inconclusive=True,
        )

    # 쿠키 파일을 가리키지 않게 하고, 자동 재로그인도 끈 사본으로 조회한다.
    anonymous_source = dataclasses.replace(
        config.source,
        storage_state="/nonexistent-on-purpose.json",
        login=dataclasses.replace(config.source.login, enabled=False),
    )
    adapter = ApiAdapter(
        anonymous_source, config.target.hall_code, timeout=config.poll.timeout_seconds
    )
    year, month = parse_month(config.target.months[0])
    try:
        slots = adapter.fetch_month(year, month)
    except LoginRequired as exc:
        return ProbeResult(login_required=True, detail=str(exc))
    except FetchError as exc:
        # 로그인 문제인지 단순 오류인지 구분할 수 없다.
        return ProbeResult(login_required=True, detail=str(exc), inconclusive=True)
    finally:
        adapter.close()

    return ProbeResult(
        login_required=False,
        detail=f"{config.target.months[0]} 조회 성공 (예약 가능 {len(slots)}건)",
        slots=slots,
    )
