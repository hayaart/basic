"""세션 만료 시 자동 재로그인."""

import json

import pytest
import responses

from wedding_watch.adapters.api import ApiAdapter, save_cookies_to_storage_state
from wedding_watch.adapters.base import LoginRequired
from wedding_watch.config import (
    ApiSourceConfig,
    ConfigError,
    LoginConfig,
    ResponseMap,
    SourceConfig,
)

SCHEDULE_URL = "https://example.test/schedule"
LOGIN_URL = "https://example.test/login.do"

PAYLOAD = {"data": {"list": [{"d": "20270508", "ok": "Y"}]}}
MAPPING = ResponseMap(items_path="data.list", date_field="d", status_field="ok", available_values=["Y"])


def make_adapter(tmp_path, enabled=True, **login_kwargs):
    login = LoginConfig(
        enabled=enabled,
        url=LOGIN_URL,
        form={"userId": "{id}", "userPw": "{password}", "rememberMe": "N"},
        username="hayaart",
        password="s3cret",
        **login_kwargs,
    )
    source = SourceConfig(
        mode="api",
        storage_state=str(tmp_path / "storage_state.json"),
        login=login,
        api=ApiSourceConfig(url=SCHEDULE_URL, method="POST", response=MAPPING),
    )
    return ApiAdapter(source, "5")


@responses.activate
def test_expired_session_triggers_relogin_and_retry(tmp_path):
    # 첫 조회는 로그인 페이지로 튕기고, 재로그인 후 두 번째 조회는 성공한다.
    responses.add(responses.POST, SCHEDULE_URL, body="<html>로그인이 필요 UWDDWSCO02M1</html>",
                  content_type="text/html", status=200)
    responses.add(responses.POST, LOGIN_URL, body="환영합니다", status=200,
                  headers={"Set-Cookie": "JSESSIONID=fresh; Path=/"})
    responses.add(responses.POST, SCHEDULE_URL, json=PAYLOAD, status=200)

    slots = make_adapter(tmp_path).fetch_month(2027, 5)

    assert [s.key for s in slots] == ["2027-05-08|"]
    assert [call.request.url for call in responses.calls] == [SCHEDULE_URL, LOGIN_URL, SCHEDULE_URL]


@responses.activate
def test_login_form_fills_credentials_from_placeholders(tmp_path):
    responses.add(responses.POST, SCHEDULE_URL, status=401, json={})
    responses.add(responses.POST, LOGIN_URL, body="ok", status=200,
                  headers={"Set-Cookie": "JSESSIONID=fresh; Path=/"})
    responses.add(responses.POST, SCHEDULE_URL, json=PAYLOAD, status=200)

    make_adapter(tmp_path).fetch_month(2027, 5)

    body = responses.calls[1].request.body
    assert "userId=hayaart" in body
    assert "userPw=s3cret" in body
    assert "rememberMe=N" in body      # 고정 필드는 그대로 전달


@responses.activate
def test_wrong_password_does_not_retry(tmp_path):
    """비밀번호가 틀리면 즉시 멈춘다 — 반복 시도는 계정 잠김을 부른다."""
    responses.add(responses.POST, SCHEDULE_URL, status=401, json={})
    responses.add(responses.POST, LOGIN_URL, body="비밀번호가 일치하지 않습니다", status=200)

    with pytest.raises(LoginRequired, match="아이디/비밀번호"):
        make_adapter(tmp_path).fetch_month(2027, 5)

    assert len(responses.calls) == 2      # 조회 재시도 없음


@responses.activate
def test_relogin_persists_cookies_for_next_run(tmp_path):
    responses.add(responses.POST, SCHEDULE_URL, status=401, json={})
    responses.add(responses.POST, LOGIN_URL, body="ok", status=200,
                  headers={"Set-Cookie": "JSESSIONID=fresh; Path=/"})
    responses.add(responses.POST, SCHEDULE_URL, json=PAYLOAD, status=200)

    adapter = make_adapter(tmp_path)
    adapter.fetch_month(2027, 5)

    saved = json.loads((tmp_path / "storage_state.json").read_text(encoding="utf-8"))
    assert {c["name"]: c["value"] for c in saved["cookies"]}["JSESSIONID"] == "fresh"


@responses.activate
def test_relogin_disabled_propagates_login_required(tmp_path):
    responses.add(responses.POST, SCHEDULE_URL, status=401, json={})
    with pytest.raises(LoginRequired):
        make_adapter(tmp_path, enabled=False).fetch_month(2027, 5)
    assert len(responses.calls) == 1      # 로그인 시도조차 하지 않는다


@responses.activate
def test_login_without_cookies_is_treated_as_failure(tmp_path):
    responses.add(responses.POST, SCHEDULE_URL, status=401, json={})
    responses.add(responses.POST, LOGIN_URL, body="ok", status=200)   # Set-Cookie 없음
    with pytest.raises(LoginRequired, match="쿠키가 없습니다"):
        make_adapter(tmp_path).fetch_month(2027, 5)


def test_saving_cookies_keeps_unrelated_ones(tmp_path):
    path = tmp_path / "storage_state.json"
    path.write_text(json.dumps({
        "cookies": [{"name": "other", "value": "keep"}, {"name": "JSESSIONID", "value": "stale"}],
        "origins": [],
    }), encoding="utf-8")

    import requests
    jar = requests.Session().cookies
    jar.set("JSESSIONID", "fresh", domain="example.test", path="/")

    save_cookies_to_storage_state(path, jar)

    saved = {c["name"]: c["value"] for c in json.loads(path.read_text())["cookies"]}
    assert saved == {"other": "keep", "JSESSIONID": "fresh"}


def test_credentials_must_come_from_env_not_yaml():
    login = LoginConfig(enabled=True, url=LOGIN_URL, form={"a": "{id}"})
    with pytest.raises(ConfigError, match="WW_LOGIN_ID"):
        login.validate()


def test_enabled_login_requires_url():
    source = SourceConfig(
        mode="api",
        login=LoginConfig(enabled=True, username="u", password="p"),
        api=ApiSourceConfig(url=SCHEDULE_URL),
    )
    with pytest.raises(ConfigError, match="source.login.url"):
        source.validate()
