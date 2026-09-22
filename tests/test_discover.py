from wedding_watch.discover import analyze_records, find_record_lists, suggest_configs

PAYLOAD = {
    "resultCode": "0000",
    "data": {
        "scheduleList": [
            {"WEDG_YMD": "20270508", "RSVT_PSBL_YN": "Y", "WEDG_TM": "11:00"},
            {"WEDG_YMD": "20270515", "RSVT_PSBL_YN": "N", "WEDG_TM": "13:30"},
        ]
    },
}


def test_find_record_lists():
    paths = [path for path, _ in find_record_lists(PAYLOAD)]
    assert "data.scheduleList" in paths


def test_analyze_identifies_date_status_and_time_fields():
    analysis = analyze_records(PAYLOAD["data"]["scheduleList"])
    assert analysis["date_field"] == "WEDG_YMD"
    assert analysis["status_candidates"][0][0] == "RSVT_PSBL_YN"
    assert sorted(analysis["status_candidates"][0][1]) == ["N", "Y"]
    assert analysis["time_candidates"] == ["WEDG_TM"]


def test_analyze_returns_none_without_dates():
    assert analyze_records([{"name": "홀A", "seats": 200}]) is None


def test_suggest_prefers_the_biggest_record_list():
    captured = [
        {"url": "https://x/small", "method": "GET", "post_data": None,
         "payload": {"list": [{"d": "20270508"}]}},
        {"url": "https://x/big", "method": "POST", "post_data": "{}",
         "payload": {"list": [{"d": f"2027050{i}"} for i in range(1, 10)]}},
    ]
    suggestions = suggest_configs(captured)
    assert suggestions[0]["entry"]["url"].endswith("/big")
    assert suggestions[0]["items_path"] == "list"
