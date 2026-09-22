import base64

import responses

from wedding_watch.config import NtfyConfig
from wedding_watch.models import Slot
from wedding_watch.notify import Notifier, _encode_header


def test_korean_header_is_rfc2047_encoded():
    encoded = _encode_header("삼성금융연수원")
    assert encoded.startswith("=?UTF-8?B?")
    payload = encoded[len("=?UTF-8?B?") : -2]
    assert base64.b64decode(payload).decode("utf-8") == "삼성금융연수원"
    encoded.encode("latin-1")  # ntfy 헤더로 실을 수 있어야 한다


def test_ascii_header_is_left_alone():
    assert _encode_header("plain title") == "plain title"


@responses.activate
def test_new_slots_message_lists_dates():
    responses.add(responses.POST, "https://ntfy.sh/my-topic", status=200)
    notifier = Notifier(NtfyConfig(topic="my-topic"))

    assert notifier.notify_new_slots(
        [Slot("2027-05-15", "11:00"), Slot("2027-05-08", "13:30")], "삼성금융연수원"
    )

    request = responses.calls[0].request
    body = request.body.decode("utf-8")
    assert "2027-05-08(토) 13:30" in body
    assert body.index("2027-05-08") < body.index("2027-05-15")  # 날짜순 정렬
    assert request.headers["Priority"] == "urgent"


@responses.activate
def test_long_list_is_truncated():
    responses.add(responses.POST, "https://ntfy.sh/my-topic", status=200)
    slots = [Slot(f"2027-05-{day:02d}") for day in range(1, 32)]
    Notifier(NtfyConfig(topic="my-topic")).notify_new_slots(slots, "홀")
    body = responses.calls[0].request.body.decode("utf-8")
    assert "외 1건" in body


@responses.activate
def test_token_and_custom_server():
    responses.add(responses.POST, "https://ntfy.example.com/t", status=200)
    notifier = Notifier(NtfyConfig(topic="t", server="https://ntfy.example.com/", token="tk_1"))
    assert notifier.send("hi", "title")
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tk_1"


@responses.activate
def test_send_failure_does_not_raise():
    responses.add(responses.POST, "https://ntfy.sh/my-topic", status=500)
    assert Notifier(NtfyConfig(topic="my-topic")).send("hi", "title") is False
