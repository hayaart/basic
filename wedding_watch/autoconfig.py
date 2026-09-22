"""캡처 결과를 config.yaml 에 자동으로 써 넣는다.

비개발자가 YAML 을 손으로 편집하지 않아도 되게 하는 것이 목적이다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

YM_RE = re.compile(r"\b20\d{2}(0[1-9]|1[0-2])\b")          # 202705
YM_DASH_RE = re.compile(r"\b20\d{2}-(0[1-9]|1[0-2])\b")    # 2027-05
HALL_KEY_HINTS = ("hll", "hall", "홀")


def templatize(value: Any, hall_code: str, key: str = "") -> Any:
    """캡처된 값 안의 '조회한 연월'을 자리표시자로 바꾼다.

    연월만 매달 달라지므로 그것만 확실히 바꾸고, 홀 코드는 키 이름이 홀처럼
    보일 때만 바꾼다. (홀 코드는 어차피 5 로 고정이라 그냥 둬도 동작한다.)
    """
    if isinstance(value, dict):
        return {k: templatize(v, hall_code, k) for k, v in value.items()}
    if isinstance(value, list):
        return [templatize(v, hall_code, key) for v in value]
    if not isinstance(value, str):
        return value

    result = YM_DASH_RE.sub("{year_month}", value)
    result = YM_RE.sub("{ym}", result)
    if hall_code and result == hall_code and any(h in key.lower() for h in HALL_KEY_HINTS):
        result = "{hall_code}"
    return result


def split_query(url: str) -> tuple[str, dict[str, str]]:
    """URL 을 주소와 쿼리 파라미터로 나눈다."""
    base, _, query = url.partition("?")
    params: dict[str, str] = {}
    for pair in query.split("&"):
        if "=" in pair:
            name, _, value = pair.partition("=")
            params[name] = value
    return base, params


def parse_post_data(raw: str | None) -> tuple[dict[str, Any] | None, bool]:
    """POST 본문을 dict 로. (본문, JSON 여부) 를 돌려준다."""
    if not raw:
        return None, False
    text = raw.strip()
    if text.startswith(("{", "[")):
        import json

        try:
            parsed = json.loads(text)
        except ValueError:
            return None, False
        return (parsed, True) if isinstance(parsed, dict) else (None, False)
    body = {}
    for pair in text.split("&"):
        if "=" in pair:
            name, _, value = pair.partition("=")
            body[name] = value
    return (body or None), False


def build_api_section(suggestion: dict[str, Any], hall_code: str) -> dict[str, Any]:
    """discover 후보 하나를 config 의 source.api 블록으로 바꾼다."""
    entry = suggestion["entry"]
    base_url, params = split_query(entry["url"])
    body, is_json = parse_post_data(entry.get("post_data"))

    response: dict[str, Any] = {
        "items_path": suggestion["items_path"],
        "date_field": suggestion["date_field"],
    }
    if suggestion.get("time_candidates"):
        response["time_field"] = suggestion["time_candidates"][0]
    if suggestion.get("status_candidates"):
        field, values = suggestion["status_candidates"][0]
        response["status_field"] = field
        # 'Y' / '가능' 처럼 예약 가능해 보이는 값만 남긴다.
        positive = [v for v in values if v.strip().lower() in {"y", "yes", "true", "1", "가능"}]
        response["available_values"] = positive or values

    section: dict[str, Any] = {
        "url": templatize(base_url, hall_code),
        "method": entry.get("method", "GET").upper(),
        "params": templatize(params, hall_code),
        "response": response,
    }
    if body is not None:
        section["body"] = templatize(body, hall_code)
        section["body_is_json"] = is_json
    return section


def build_login_section(form_post: dict[str, Any]) -> dict[str, Any]:
    """캡처한 로그인 폼(필드 이름만)을 source.login 블록으로 바꾼다."""
    from .discover import _guess_field

    names = form_post["field_names"]
    id_field = _guess_field(names, ("id", "user", "mbr", "login"))
    pw_field = _guess_field(names, ("pw", "pass", "pwd"))
    form = {}
    for name in names:
        if name == id_field:
            form[name] = "{id}"
        elif name == pw_field:
            form[name] = "{password}"
        else:
            form[name] = ""
    return {
        "enabled": True,
        "url": form_post["url"].split("?")[0],
        "method": "POST",
        "form": form,
    }


def apply_to_config(
    config_path: str | Path,
    api_section: dict[str, Any] | None = None,
    login_section: dict[str, Any] | None = None,
) -> Path:
    """config.yaml 의 해당 블록만 갈아 끼우고 다시 저장한다."""
    config_path = Path(config_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    source = data.setdefault("source", {})
    if api_section is not None:
        existing = source.get("api") or {}
        # headers 처럼 사용자가 넣어둔 값은 살린다.
        merged = {**{k: v for k, v in existing.items() if k == "headers"}, **api_section}
        source["api"] = merged
        source["mode"] = "api"
    if login_section is not None:
        source["login"] = {**(source.get("login") or {}), **login_section}
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )
    return config_path
