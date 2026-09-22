import json

import pytest
import requests
import responses

from wedding_watch.adapters.api import ApiAdapter, cookies_from_storage_state, dig, extract_slots
from wedding_watch.adapters.base import FetchError, LoginRequired, render, template_vars
from wedding_watch.config import ApiSourceConfig, ResponseMap, SourceConfig

PAYLOAD = {
    "resultCode": "0000",
    "data": {
        "list": [
            {"WEDG_YMD": "20270508", "RSVT_PSBL_YN": "Y", "WEDG_TM": "11:00", "HLL_NM": "대강당"},
            {"WEDG_YMD": "20270508", "RSVT_PSBL_YN": "N", "WEDG_TM": "13:30", "HLL_NM": "대강당"},
            {"WEDG_YMD": "2027-05-15", "RSVT_PSBL_YN": "Y", "WEDG_TM": "11:00", "HLL_NM": "대강당"},
        ]
    },
}

MAPPING = ResponseMap(
    items_path="data.list",
    date_field="WEDG_YMD",
    time_field="WEDG_TM",
    status_field="RSVT_PSBL_YN",
    available_values=["Y"],
    label_field="HLL_NM",
)


def test_dig_walks_dicts_and_lists():
    assert dig({"a": {"b": [10, 20]}}, "a.b.1") == 20
    assert dig({"a": 1}, "a.missing.deep") is None


def test_extract_only_available_slots():
    slots = extract_slots(PAYLOAD, MAPPING)
    assert [s.key for s in slots] == ["2027-05-08|11:00", "2027-05-15|11:00"]
    assert slots[0].label == "대강당"


def test_extract_without_status_field_keeps_everything():
    mapping = ResponseMap(items_path="data.list", date_field="WEDG_YMD")
    assert len(extract_slots(PAYLOAD, mapping)) == 3


def test_extract_skips_unparseable_dates():
    payload = {"list": [{"d": "미정"}, {"d": "20271004"}]}
    slots = extract_slots(payload, ResponseMap(items_path="list", date_field="d"))
    assert [s.date for s in slots] == ["2027-10-04"]


def test_wrong_items_path_explains_itself():
    with pytest.raises(FetchError, match="items_path"):
        extract_slots(PAYLOAD, ResponseMap(items_path="data.nope", date_field="d"))


def test_template_rendering():
    variables = template_vars("5", 2027, 9)
    assert render("hall={hall_code}&ym={ym}", variables) == "hall=5&ym=202709"
    assert render({"a": ["{year_month}"]}, variables) == {"a": ["2027-09"]}


def test_template_rejects_unknown_placeholder():
    with pytest.raises(FetchError, match="자리표시자"):
        render("{unknown}", template_vars("5", 2027, 9))


def _adapter(**api_kwargs):
    api = ApiSourceConfig(
        url="https://example.test/schedule?ym={ym}",
        method="POST",
        body={"WEDG_HLL_C": "{hall_code}", "SRCH_YM": "{ym}"},
        response=MAPPING,
        **api_kwargs,
    )
    return ApiAdapter(SourceConfig(mode="api", api=api, storage_state="/nonexistent.json"), "5")


@responses.activate
def test_fetch_month_sends_templated_body_and_parses():
    responses.add(responses.POST, "https://example.test/schedule", json=PAYLOAD, status=200)
    slots = _adapter().fetch_month(2027, 5)
    assert [s.key for s in slots] == ["2027-05-08|11:00", "2027-05-15|11:00"]
    request = responses.calls[0].request
    assert json.loads(request.body) == {"WEDG_HLL_C": "5", "SRCH_YM": "202705"}
    assert "ym=202705" in request.url


@responses.activate
def test_login_page_response_raises_login_required():
    responses.add(
        responses.POST,
        "https://example.test/schedule",
        body="<html>로그인이 필요합니다 UWDDWSCO02M1</html>",
        content_type="text/html",
        status=200,
    )
    with pytest.raises(LoginRequired):
        _adapter().fetch_month(2027, 5)


@responses.activate
def test_401_raises_login_required():
    responses.add(responses.POST, "https://example.test/schedule", json={}, status=401)
    with pytest.raises(LoginRequired):
        _adapter().fetch_month(2027, 5)


@responses.activate
def test_server_error_raises_fetch_error():
    responses.add(responses.POST, "https://example.test/schedule", json={}, status=500)
    with pytest.raises(FetchError, match="HTTP 500"):
        _adapter().fetch_month(2027, 5)


@responses.activate
def test_network_error_raises_fetch_error():
    responses.add(responses.POST, "https://example.test/schedule", body=requests.ConnectionError("끊김"))
    with pytest.raises(FetchError, match="요청 실패"):
        _adapter().fetch_month(2027, 5)


def test_cookies_from_storage_state(tmp_path):
    path = tmp_path / "storage_state.json"
    path.write_text(
        json.dumps({"cookies": [{"name": "JSESSIONID", "value": "abc123"}]}), encoding="utf-8"
    )
    assert cookies_from_storage_state(path) == {"JSESSIONID": "abc123"}
    assert cookies_from_storage_state(tmp_path / "missing.json") == {}
