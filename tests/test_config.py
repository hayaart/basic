import pytest

from wedding_watch.config import Config, ConfigError, apply_env_overrides, load_config

BASE = """
target:
  hall_code: "5"
  hall_name: "삼성금융연수원"
  months: ["2027-05", "2027-06", "2027-09", "2027-10", "2027-11"]
ntfy:
  topic: "my-secret-topic"
source:
  mode: "api"
  api:
    url: "https://example.test/schedule"
    response:
      items_path: "data.list"
"""


def write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_nested_config(tmp_path):
    config = load_config(write(tmp_path, BASE), environ={})
    assert config.target.hall_code == "5"
    assert config.target.months[0] == "2027-05"
    assert config.poll.interval_seconds == 600  # 기본값 10분
    assert config.source.api.response.items_path == "data.list"


def test_env_overrides_win(tmp_path):
    config = load_config(
        write(tmp_path, BASE),
        environ={"WW_NTFY_TOPIC": "from-env", "WW_MONTHS": "2027-05, 2027-10"},
    )
    assert config.ntfy.topic == "from-env"
    assert config.target.months == ["2027-05", "2027-10"]


def test_blank_env_does_not_clobber(tmp_path):
    config = load_config(write(tmp_path, BASE), environ={"WW_NTFY_TOPIC": ""})
    assert config.ntfy.topic == "my-secret-topic"


def test_missing_topic_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="ntfy.topic"):
        load_config(write(tmp_path, BASE.replace('topic: "my-secret-topic"', 'topic: ""')), environ={})


def test_bad_month_format_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="YYYY-MM"):
        load_config(write(tmp_path, BASE.replace('"2027-05"', '"2027/05"')), environ={})


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="알 수 없는 설정 키"):
        load_config(write(tmp_path, BASE + "\nbogus: 1\n"), environ={})


def test_too_frequent_polling_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="interval_seconds"):
        load_config(write(tmp_path, BASE + "\npoll:\n  interval_seconds: 5\n"), environ={})


def test_api_mode_requires_url(tmp_path):
    with pytest.raises(ConfigError, match="source.api.url"):
        load_config(write(tmp_path, BASE.replace('url: "https://example.test/schedule"', 'url: ""')), environ={})


def test_missing_file_message(tmp_path):
    with pytest.raises(ConfigError, match="찾을 수 없습니다"):
        load_config(tmp_path / "nope.yaml", environ={})


def test_int_env_is_cast():
    config = Config()
    apply_env_overrides(config, {"WW_INTERVAL_SECONDS": "900"})
    assert config.poll.interval_seconds == 900
