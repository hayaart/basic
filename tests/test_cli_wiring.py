"""CLI 가 설정 단계 명령을 막지 않는지 확인."""

import pytest
import yaml

from wedding_watch.cli import main
from wedding_watch.setup_wizard import generate_topic, write_env

MINIMAL = {
    "target": {"hall_code": "5", "months": ["2027-05"]},
    "ntfy": {"topic": "t"},
    "source": {"mode": "api", "api": {"url": ""}},   # 아직 discover 전
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(MINIMAL, allow_unicode=True), encoding="utf-8")
    return path


def test_state_works_before_discover(config_file, capsys):
    """api.url 이 비어 있어도 설정 단계 명령은 동작해야 한다."""
    assert main(["-c", str(config_file), "state"]) == 0


def test_check_still_requires_a_configured_source(config_file, capsys):
    assert main(["-c", str(config_file), "check"]) == 2
    assert "source.api.url" in capsys.readouterr().err


def test_missing_config_points_at_setup(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["-c", "nope.yaml", "state"]) == 2
    assert "wedding-watch setup" in capsys.readouterr().err


def test_generated_topic_is_unguessable():
    topic = generate_topic()
    assert topic.startswith("wedding-") and len(topic) > 16
    assert topic != generate_topic()


def test_write_env_updates_and_locks_permissions(tmp_path):
    env = tmp_path / ".env"
    env.write_text("WW_NTFY_TOPIC=old\nOTHER=keep\n", encoding="utf-8")

    write_env(env, {"WW_NTFY_TOPIC": "new", "WW_LOGIN_ID": "me"})

    text = env.read_text(encoding="utf-8")
    assert "WW_NTFY_TOPIC=new" in text
    assert "OTHER=keep" in text
    assert "WW_LOGIN_ID=me" in text
    assert oct(env.stat().st_mode)[-3:] == "600"


def test_month_prompt_reasks_until_valid(monkeypatch, capsys):
    from wedding_watch.setup_wizard import ask_months

    answers = iter(["2027년 5월", "2027-5", "2027-05, 2027-11"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert ask_months("월", ["2027-05"]) == ["2027-05", "2027-11"]
    assert "형식이 올바르지 않습니다" in capsys.readouterr().out


def test_month_prompt_accepts_default_on_enter(monkeypatch):
    from wedding_watch.setup_wizard import ask_months

    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ask_months("월", ["2027-09"]) == ["2027-09"]


def test_nonempty_prompt_reasks(monkeypatch):
    from wedding_watch.setup_wizard import ask_nonempty

    answers = iter(["", "  ", "삼성금융연수원"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert ask_nonempty("이름") == "삼성금융연수원"
