"""로그인이 실제로 필요한지 측정한다."""

import responses

from wedding_watch.config import (
    ApiSourceConfig,
    Config,
    LoginConfig,
    NtfyConfig,
    ResponseMap,
    SourceConfig,
    TargetConfig,
)
from wedding_watch.probe import probe_without_login

URL = "https://example.test/schedule"


def make_config(tmp_path, mode="api"):
    return Config(
        target=TargetConfig(hall_code="5", months=["2027-05"]),
        ntfy=NtfyConfig(topic="t"),
        state_file=str(tmp_path / "seen.json"),
        source=SourceConfig(
            mode=mode,
            storage_state=str(tmp_path / "storage_state.json"),
            login=LoginConfig(enabled=True, url="https://example.test/login", username="u", password="p"),
            api=ApiSourceConfig(
                url=URL,
                method="GET",
                response=ResponseMap(items_path="list", date_field="d"),
            ),
        ),
    )


@responses.activate
def test_public_endpoint_is_detected(tmp_path):
    responses.add(responses.GET, URL, json={"list": [{"d": "20270508"}]}, status=200)

    result = probe_without_login(make_config(tmp_path))

    assert result.login_required is False
    assert result.inconclusive is False
    assert "조회 성공" in result.detail
    assert "로그인 없이도 조회됩니다" in result.summary()


@responses.activate
def test_login_wall_is_detected(tmp_path):
    responses.add(responses.GET, URL, body="<html>로그인이 필요 UWDDWSCO02M1</html>",
                  content_type="text/html", status=200)

    result = probe_without_login(make_config(tmp_path))

    assert result.login_required is True
    assert result.inconclusive is False


@responses.activate
def test_probe_does_not_use_saved_cookies_or_autologin(tmp_path):
    """쿠키가 있어도 무시해야 '로그인 없이 되는지'를 측정할 수 있다."""
    storage = tmp_path / "storage_state.json"
    storage.write_text('{"cookies": [{"name": "JSESSIONID", "value": "valid"}]}', encoding="utf-8")
    responses.add(responses.GET, URL, status=401, json={})

    result = probe_without_login(make_config(tmp_path))

    assert result.login_required is True
    # 자동 로그인이 켜져 있어도 로그인을 시도하지 않는다 (시도하면 측정이 무의미해진다).
    assert len(responses.calls) == 1
    assert "Cookie" not in responses.calls[0].request.headers


@responses.activate
def test_server_error_is_inconclusive(tmp_path):
    responses.add(responses.GET, URL, status=500, json={})

    result = probe_without_login(make_config(tmp_path))

    assert result.inconclusive is True
    assert "판단 불가" in result.summary()


def test_browser_mode_is_inconclusive(tmp_path):
    config = make_config(tmp_path, mode="browser")
    result = probe_without_login(config)
    assert result.inconclusive is True
    assert "시크릿 창" in result.detail


@responses.activate
def test_probe_leaves_the_real_config_untouched(tmp_path):
    """측정용 사본만 바꾸고 원래 설정은 그대로여야 한다."""
    config = make_config(tmp_path)
    responses.add(responses.GET, URL, json={"list": []}, status=200)

    probe_without_login(config)

    assert config.source.login.enabled is True
    assert config.source.storage_state == str(tmp_path / "storage_state.json")


def test_test_public_does_not_require_credentials(tmp_path, monkeypatch, capsys):
    """로그인이 필요한지 '확인하는' 명령이 자격증명을 요구하면 앞뒤가 안 맞는다."""
    import yaml

    from wedding_watch.cli import main

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target": {"hall_code": "5", "months": ["2027-05"]},
                "ntfy": {"topic": "t"},
                "source": {
                    "mode": "api",
                    # 자동 로그인은 켜져 있지만 .env 에 아이디/비밀번호가 없는 상태
                    "login": {"enabled": True, "url": "https://example.test/login"},
                    "api": {"url": URL, "response": {"items_path": "list", "date_field": "d"}},
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with responses.RequestsMock() as mock:
        mock.add(responses.GET, URL, json={"list": [{"d": "20270508"}]}, status=200)
        assert main(["-c", str(path), "test-public"]) == 0

    assert "로그인 없이도 조회됩니다" in capsys.readouterr().out


def test_run_still_requires_credentials_when_autologin_is_on(tmp_path, monkeypatch, capsys):
    import yaml

    from wedding_watch.cli import main

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target": {"hall_code": "5", "months": ["2027-05"]},
                "ntfy": {"topic": "t"},
                "source": {
                    "mode": "api",
                    "login": {"enabled": True, "url": "https://example.test/login"},
                    "api": {"url": URL, "response": {"items_path": "list", "date_field": "d"}},
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    assert main(["-c", str(path), "check"]) == 2
    assert "WW_LOGIN_ID" in capsys.readouterr().err
