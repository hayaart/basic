"""사이트가 쓰는 JSON API 를 그대로 호출하는 어댑터 (가볍고 빠름)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

from ..config import ApiSourceConfig, ResponseMap, SourceConfig
from ..models import Slot, normalize_date
from .base import Adapter, FetchError, LoginRequired, render, template_vars

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
}


def cookies_from_storage_state(path: str | Path) -> dict[str, str]:
    """Playwright storage_state.json 에서 쿠키를 꺼낸다."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise FetchError(f"세션 파일을 읽을 수 없습니다: {path} ({exc})") from exc
    return {c["name"]: c["value"] for c in data.get("cookies", []) if "name" in c}


def save_cookies_to_storage_state(path: str | Path, jar) -> None:
    """재로그인으로 갱신된 쿠키를 Playwright storage_state 형식으로 되돌려 저장한다.

    다음 실행(cron 등)이 로그인을 다시 하지 않고 바로 쓸 수 있게 한다.
    """
    path = Path(path)
    data: dict[str, Any] = {"cookies": [], "origins": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data.setdefault("origins", [])
    fresh = {}
    for cookie in jar:
        fresh[cookie.name] = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "expires": float(cookie.expires) if cookie.expires else -1,
            "httpOnly": False,
            "secure": bool(cookie.secure),
            "sameSite": "Lax",
        }
    kept = [c for c in data.get("cookies", []) if c.get("name") not in fresh]
    data["cookies"] = kept + list(fresh.values())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dig(data: Any, path: str) -> Any:
    """'data.list' 또는 'data.0.list' 같은 경로로 중첩 값을 꺼낸다."""
    if not path:
        return data
    current = data
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def extract_slots(payload: Any, mapping: ResponseMap) -> list[Slot]:
    """응답 JSON에서 '예약 가능' 슬롯만 뽑는다."""
    items = dig(payload, mapping.items_path)
    if items is None:
        raise FetchError(
            f"응답에서 items_path={mapping.items_path!r} 를 찾지 못했습니다. "
            "config 의 source.api.response 설정을 확인하세요."
        )
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        raise FetchError(f"items_path 가 가리키는 값이 목록이 아닙니다: {type(items).__name__}")

    available = {str(v).strip().lower() for v in mapping.available_values}
    slots: list[Slot] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if mapping.status_field:
            status = str(dig(item, mapping.status_field) or "").strip().lower()
            if status not in available:
                continue
        raw_date = dig(item, mapping.date_field)
        if raw_date in (None, ""):
            continue
        try:
            date = normalize_date(raw_date, mapping.date_format)
        except ValueError as exc:
            log.warning("날짜 해석 실패, 건너뜀: %s", exc)
            continue
        time = ""
        if mapping.time_field:
            time = str(dig(item, mapping.time_field) or "").strip()
        label = ""
        if mapping.label_field:
            label = str(dig(item, mapping.label_field) or "").strip()
        slots.append(Slot(date=date, time=time, label=label))
    return slots


class ApiAdapter(Adapter):
    def __init__(
        self,
        source: SourceConfig,
        hall_code: str,
        timeout: int = 30,
        session: requests.Session | None = None,
    ):
        self.source = source
        self.api: ApiSourceConfig = source.api
        self.hall_code = hall_code
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers.update(self.api.headers)
        cookies = cookies_from_storage_state(source.storage_state)
        if cookies:
            self.session.cookies.update(cookies)
            log.debug("세션 쿠키 %d개 로드", len(cookies))

    def fetch_month(self, year: int, month: int) -> list[Slot]:
        try:
            return self._fetch_month(year, month)
        except LoginRequired:
            if not self.source.login.enabled:
                raise
            # 세션이 만료됐을 뿐이므로 한 번 다시 로그인하고 재시도한다.
            log.info("세션이 만료된 것 같습니다. 자동 재로그인을 시도합니다.")
            self.login()
            return self._fetch_month(year, month)

    def login(self) -> None:
        """아이디/비밀번호로 다시 로그인하고 갱신된 쿠키를 저장한다."""
        login = self.source.login
        payload = {
            key: value.format(id=login.username, password=login.password)
            for key, value in login.form.items()
        }
        kwargs: dict[str, Any] = {"timeout": self.timeout, "headers": login.headers or None}
        if login.form_is_json:
            kwargs["json"] = payload
        else:
            kwargs["data"] = payload
        try:
            response = self.session.request(login.method.upper(), login.url, **kwargs)
        except requests.RequestException as exc:
            raise LoginRequired(f"로그인 요청 실패: {exc}") from exc

        if response.status_code >= 400:
            raise LoginRequired(f"로그인 실패 (HTTP {response.status_code}).")
        body = response.text[:4000]
        for marker in login.failure_markers:
            if marker and marker in body:
                # 비밀번호가 틀린 것이므로 재시도해도 소용없다. 계정 잠김을 피하려면 여기서 멈춰야 한다.
                raise LoginRequired(
                    f"로그인에 실패했습니다(아이디/비밀번호 확인 필요): {marker!r} 가 응답에 있습니다."
                )
        if not self.session.cookies:
            raise LoginRequired("로그인 응답에 쿠키가 없습니다. source.login 설정을 확인하세요.")
        log.info("자동 재로그인 성공")
        try:
            save_cookies_to_storage_state(self.source.storage_state, self.session.cookies)
        except OSError as exc:
            log.warning("갱신된 세션을 저장하지 못했습니다: %s", exc)

    def _fetch_month(self, year: int, month: int) -> list[Slot]:
        variables = template_vars(self.hall_code, year, month)
        url = render(self.api.url, variables)
        params = render(self.api.params, variables)
        body = render(self.api.body, variables) if self.api.body else None

        kwargs: dict[str, Any] = {"params": params, "timeout": self.timeout}
        if body is not None:
            if self.api.body_is_json:
                kwargs["json"] = body
            else:
                kwargs["data"] = body

        try:
            response = self.session.request(self.api.method.upper(), url, **kwargs)
        except requests.RequestException as exc:
            raise FetchError(f"요청 실패: {exc}") from exc

        self._check_login(response)
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}: {response.text[:200]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(
                f"JSON 응답이 아닙니다 (HTTP {response.status_code}). 본문 앞부분: {response.text[:200]!r}"
            ) from exc
        return extract_slots(payload, self.api.response)

    def _check_login(self, response: requests.Response) -> None:
        """로그인 페이지로 튕겼는지 확인한다."""
        if response.status_code in (401, 403):
            raise LoginRequired(f"인증 실패 (HTTP {response.status_code}). 세션을 갱신하세요.")
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type.lower():
            return
        body = response.text[:2000]
        for marker in self.source.login_required_markers:
            if marker and marker.lower() in body.lower():
                raise LoginRequired(
                    "로그인 페이지가 돌아왔습니다. `wedding-watch login` 으로 세션을 갱신하세요."
                )
