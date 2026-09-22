"""설정 로딩/검증.

YAML 파일을 읽고 환경변수(WW_*)로 덮어쓴다. 비밀값(ntfy 토큰, 로그인 정보)은
YAML 대신 환경변수/.env 로 넣는 것을 권장한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ConfigError(ValueError):
    """설정이 잘못되었을 때."""


@dataclass
class NtfyConfig:
    topic: str = ""
    server: str = "https://ntfy.sh"
    token: str | None = None
    username: str | None = None
    password: str | None = None
    priority: str = "high"
    tags: list[str] = field(default_factory=lambda: ["wedding_ring", "bell"])
    click_url: str | None = None

    def validate(self) -> None:
        if not self.topic:
            raise ConfigError(
                "ntfy.topic 이 비어 있습니다. config.yaml 또는 WW_NTFY_TOPIC 으로 설정하세요."
            )
        if self.priority not in {"min", "low", "default", "high", "urgent"}:
            raise ConfigError(f"ntfy.priority 값이 올바르지 않습니다: {self.priority}")


@dataclass
class TargetConfig:
    hall_code: str = "5"
    hall_name: str = "삼성금융연수원"
    months: list[str] = field(default_factory=list)
    # 비어 있으면 모든 요일. 0=월 ... 6=일
    weekdays: list[int] = field(default_factory=list)
    exclude_dates: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.hall_code:
            raise ConfigError("target.hall_code 는 필수입니다.")
        if not self.months:
            raise ConfigError("target.months 가 비어 있습니다. 예: ['2027-05']")
        for month in self.months:
            if not MONTH_RE.match(month):
                raise ConfigError(f"target.months 형식은 YYYY-MM 이어야 합니다: {month!r}")
        for weekday in self.weekdays:
            if not 0 <= weekday <= 6:
                raise ConfigError(f"target.weekdays 는 0(월)~6(일) 범위입니다: {weekday}")


@dataclass
class PollConfig:
    interval_seconds: int = 600
    jitter_seconds: int = 60
    timeout_seconds: int = 30
    # 연속 실패가 이 횟수에 도달하면 '점검 필요' 알림을 한 번 보낸다.
    failure_alert_after: int = 3
    # 빈자리가 사라졌을 때도 알릴지 여부.
    notify_on_disappear: bool = False
    # 아무 일이 없어도 이 시간마다 살아있다는 알림을 보낸다. 0이면 끔.
    heartbeat_hours: int = 0

    def validate(self) -> None:
        if self.interval_seconds < 60:
            raise ConfigError("poll.interval_seconds 는 60 이상이어야 합니다 (서버 부하 방지).")
        if self.jitter_seconds < 0:
            raise ConfigError("poll.jitter_seconds 는 0 이상이어야 합니다.")
        if self.timeout_seconds <= 0:
            raise ConfigError("poll.timeout_seconds 는 1 이상이어야 합니다.")


@dataclass
class ResponseMap:
    """API 응답(JSON)에서 예약 가능 슬롯을 뽑아내는 방법."""

    items_path: str = ""
    date_field: str = "date"
    time_field: str | None = None
    status_field: str | None = None
    available_values: list[str] = field(default_factory=lambda: ["Y", "가능", "true", "1"])
    label_field: str | None = None
    # 날짜 문자열이 20270508 처럼 구분자가 없을 때 사용.
    date_format: str | None = None


@dataclass
class ApiSourceConfig:
    url: str = ""
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    body_is_json: bool = True
    response: ResponseMap = field(default_factory=ResponseMap)

    def validate(self) -> None:
        if not self.url:
            raise ConfigError(
                "source.api.url 이 비어 있습니다. `wedding-watch discover` 로 실제 요청을 캡처한 뒤 채워 넣으세요."
            )
        if self.method.upper() not in {"GET", "POST"}:
            raise ConfigError(f"source.api.method 는 GET/POST 만 지원합니다: {self.method}")


@dataclass
class BrowserSourceConfig:
    url_template: str = ""
    wait_selector: str = ""
    # 예약 가능한 날짜 셀을 고르는 선택자.
    day_selector: str = ""
    # 날짜를 읽을 속성. 비우면 셀 텍스트에서 숫자를 추출한다.
    date_attr: str | None = None
    time_selector: str | None = None
    headless: bool = True
    extra_wait_ms: int = 1500

    def validate(self) -> None:
        if not self.url_template:
            raise ConfigError("source.browser.url_template 이 비어 있습니다.")
        if not self.day_selector:
            raise ConfigError("source.browser.day_selector 가 비어 있습니다.")


@dataclass
class SourceConfig:
    mode: str = "api"
    # Playwright storage state(로그인 쿠키) 경로.
    storage_state: str = "state/storage_state.json"
    login_url: str = "https://s-wedding.samsungcard.com/login/UWDDWSCO02M1.jsp"
    # 응답에 이 문자열이 있으면 로그인이 풀린 것으로 본다.
    login_required_markers: list[str] = field(
        default_factory=lambda: ["로그인", "login", "UWDDWSCO02M1"]
    )
    api: ApiSourceConfig = field(default_factory=ApiSourceConfig)
    browser: BrowserSourceConfig = field(default_factory=BrowserSourceConfig)

    def validate(self) -> None:
        if self.mode not in {"api", "browser"}:
            raise ConfigError(f"source.mode 는 api 또는 browser 여야 합니다: {self.mode}")
        if self.mode == "api":
            self.api.validate()
        else:
            self.browser.validate()


@dataclass
class Config:
    target: TargetConfig = field(default_factory=TargetConfig)
    poll: PollConfig = field(default_factory=PollConfig)
    source: SourceConfig = field(default_factory=SourceConfig)
    ntfy: NtfyConfig = field(default_factory=NtfyConfig)
    state_file: str = "state/seen.json"

    def validate(self) -> None:
        self.target.validate()
        self.poll.validate()
        self.source.validate()
        self.ntfy.validate()


def _build(cls: type, data: Any):
    """중첩 dataclass를 dict에서 재귀적으로 만든다. 모르는 키는 에러."""
    if not isinstance(data, dict):
        raise ConfigError(f"{cls.__name__} 설정은 매핑이어야 합니다: {data!r}")
    fields = {f.name: f for f in cls.__dataclass_fields__.values()}
    unknown = set(data) - set(fields)
    if unknown:
        raise ConfigError(f"{cls.__name__}: 알 수 없는 설정 키 {sorted(unknown)}")
    kwargs = {}
    for name, value in data.items():
        nested = _NESTED.get((cls, name))
        if nested is not None and value is not None:
            kwargs[name] = _build(nested, value)
        else:
            kwargs[name] = value
    return cls(**kwargs)


_NESTED: dict[tuple[type, str], type] = {
    (Config, "target"): TargetConfig,
    (Config, "poll"): PollConfig,
    (Config, "source"): SourceConfig,
    (Config, "ntfy"): NtfyConfig,
    (SourceConfig, "api"): ApiSourceConfig,
    (SourceConfig, "browser"): BrowserSourceConfig,
    (ApiSourceConfig, "response"): ResponseMap,
}

# 환경변수 -> (설정 경로, 변환 함수)
_ENV_OVERRIDES: dict[str, tuple[tuple[str, ...], Any]] = {
    "WW_NTFY_TOPIC": (("ntfy", "topic"), str),
    "WW_NTFY_SERVER": (("ntfy", "server"), str),
    "WW_NTFY_TOKEN": (("ntfy", "token"), str),
    "WW_NTFY_USERNAME": (("ntfy", "username"), str),
    "WW_NTFY_PASSWORD": (("ntfy", "password"), str),
    "WW_NTFY_PRIORITY": (("ntfy", "priority"), str),
    "WW_HALL_CODE": (("target", "hall_code"), str),
    "WW_HALL_NAME": (("target", "hall_name"), str),
    "WW_MONTHS": (("target", "months"), lambda v: [s.strip() for s in v.split(",") if s.strip()]),
    "WW_INTERVAL_SECONDS": (("poll", "interval_seconds"), int),
    "WW_STORAGE_STATE": (("source", "storage_state"), str),
    "WW_STATE_FILE": (("state_file",), str),
    "WW_SOURCE_MODE": (("source", "mode"), str),
}


def apply_env_overrides(config: Config, environ: dict[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    for key, (path, caster) in _ENV_OVERRIDES.items():
        raw = env.get(key)
        if raw is None or raw == "":
            continue
        target: Any = config
        for part in path[:-1]:
            target = getattr(target, part)
        setattr(target, path[-1], caster(raw))
    return config


def load_config(path: str | Path, environ: dict[str, str] | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"설정 파일을 찾을 수 없습니다: {path}\n"
            "config.example.yaml 을 config.yaml 로 복사한 뒤 수정하세요."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = _build(Config, raw)
    apply_env_overrides(config, environ)
    config.validate()
    return config
