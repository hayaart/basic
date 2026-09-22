"""캡처 결과 → config.yaml 자동 반영."""

import yaml

from wedding_watch.autoconfig import (
    apply_to_config,
    build_api_section,
    build_login_section,
    parse_post_data,
    split_query,
    templatize,
)
from wedding_watch.discover import pick_login_form

SUGGESTION = {
    "entry": {
        "url": "https://s-wedding.samsungcard.com/hall/schedule.json?hallCd=5&srchYm=202705",
        "method": "POST",
        "post_data": '{"WEDG_HLL_C":"5","SRCH_YM":"202705"}',
    },
    "items_path": "data.list",
    "date_field": "WEDG_YMD",
    "time_candidates": ["WEDG_TM"],
    "status_candidates": [("RSVT_PSBL_YN", ["N", "Y"])],
    "count": 30,
}


def test_templatize_replaces_the_browsed_month():
    assert templatize("202705", "5") == "{ym}"
    assert templatize("2027-05", "5") == "{year_month}"
    assert templatize("?ym=202710&x=1", "5") == "?ym={ym}&x=1"


def test_templatize_replaces_hall_code_only_on_hall_like_keys():
    assert templatize("5", "5", key="WEDG_HLL_C") == "{hall_code}"
    assert templatize("5", "5", key="pageSize") == "5"      # 무관한 5 는 건드리지 않는다


def test_templatize_leaves_other_values_alone():
    assert templatize("대강당", "5") == "대강당"
    assert templatize(True, "5") is True
    assert templatize(None, "5") is None


def test_split_query_and_post_data():
    base, params = split_query("https://x/a?b=1&c=2")
    assert base == "https://x/a" and params == {"b": "1", "c": "2"}
    assert parse_post_data('{"a":1}') == ({"a": 1}, True)
    assert parse_post_data("a=1&b=2") == ({"a": "1", "b": "2"}, False)
    assert parse_post_data(None) == (None, False)


def test_build_api_section_from_capture():
    section = build_api_section(SUGGESTION, "5")
    assert section["url"] == "https://s-wedding.samsungcard.com/hall/schedule.json"
    # hallCd 는 이름이 '홀'처럼 보이므로 자리표시자로, srchYm 은 매달 바뀌므로 {ym} 으로.
    assert section["params"] == {"hallCd": "{hall_code}", "srchYm": "{ym}"}
    assert section["body"] == {"WEDG_HLL_C": "{hall_code}", "SRCH_YM": "{ym}"}
    assert section["body_is_json"] is True
    assert section["response"]["items_path"] == "data.list"
    assert section["response"]["time_field"] == "WEDG_TM"
    # 'N' 은 예약 가능이 아니므로 자동으로 빠진다.
    assert section["response"]["available_values"] == ["Y"]


def test_pick_login_form_needs_both_id_and_password():
    posts = [
        {"url": "https://x/search", "field_names": ["keyword", "page"]},
        {"url": "https://x/loginProc.do", "field_names": ["userId", "userPw", "saveId"]},
    ]
    assert pick_login_form(posts)["url"].endswith("loginProc.do")
    assert pick_login_form(posts[:1]) is None


def test_build_login_section_marks_credential_fields():
    section = build_login_section(
        {"url": "https://x/loginProc.do?x=1", "field_names": ["userId", "userPw", "saveId"]}
    )
    assert section["enabled"] is True
    assert section["url"] == "https://x/loginProc.do"
    assert section["form"] == {"userId": "{id}", "userPw": "{password}", "saveId": ""}


def test_apply_to_config_replaces_only_the_relevant_blocks(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target": {"hall_code": "5", "months": ["2027-05"]},
                "ntfy": {"topic": "keep-me"},
                "source": {"mode": "api", "api": {"url": "", "headers": {"Referer": "https://x"}}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    apply_to_config(path, build_api_section(SUGGESTION, "5"), {"enabled": True, "url": "https://x/l"})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["ntfy"]["topic"] == "keep-me"                        # 손대지 않음
    assert data["target"]["months"] == ["2027-05"]                   # 손대지 않음
    assert data["source"]["api"]["headers"] == {"Referer": "https://x"}  # 기존 헤더 보존
    assert data["source"]["api"]["url"].endswith("schedule.json")
    assert data["source"]["login"]["enabled"] is True
