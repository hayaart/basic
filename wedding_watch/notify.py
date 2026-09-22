"""ntfy 푸시 알림."""

from __future__ import annotations

import logging
from typing import Iterable

import requests

from .config import NtfyConfig
from .models import Slot, sort_slots

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config: NtfyConfig, timeout: int = 15, session: requests.Session | None = None):
        self.config = config
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def url(self) -> str:
        return f"{self.config.server.rstrip('/')}/{self.config.topic}"

    def _auth(self):
        if self.config.username and self.config.password:
            return (self.config.username, self.config.password)
        return None

    def send(
        self,
        message: str,
        title: str,
        priority: str | None = None,
        tags: Iterable[str] | None = None,
        click_url: str | None = None,
    ) -> bool:
        """ntfy 로 한 건 보낸다. 성공 여부를 돌려준다(알림 실패가 감시를 멈추면 안 된다)."""
        headers = {
            # ntfy 헤더는 latin-1 만 허용하므로 한글 제목은 RFC2047 로 인코딩한다.
            "Title": _encode_header(title),
            "Priority": priority or self.config.priority,
            "Markdown": "yes",
        }
        tag_list = list(tags) if tags is not None else self.config.tags
        if tag_list:
            headers["Tags"] = ",".join(tag_list)
        click = click_url or self.config.click_url
        if click:
            headers["Click"] = click
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"

        try:
            response = self.session.post(
                self.url,
                data=message.encode("utf-8"),
                headers=headers,
                auth=self._auth(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log.error("ntfy 전송 실패: %s", exc)
            return False
        log.info("ntfy 전송 완료: %s", title)
        return True

    def notify_new_slots(self, slots: list[Slot], hall_name: str, click_url: str | None = None) -> bool:
        slots = sort_slots(slots)
        count = len(slots)
        title = f"🎉 {hall_name} 빈자리 {count}건"
        lines = [f"**{hall_name}** 예약 가능 날짜가 새로 나왔습니다.", ""]
        lines += [f"- {slot.human()}" for slot in slots[:30]]
        if count > 30:
            lines.append(f"- … 외 {count - 30}건")
        lines += ["", "지금 바로 확인하세요."]
        return self.send("\n".join(lines), title, priority="urgent", click_url=click_url)

    def notify_gone_slots(self, slots: list[Slot], hall_name: str) -> bool:
        slots = sort_slots(slots)
        title = f"❌ {hall_name} 빈자리 {len(slots)}건 마감"
        lines = [f"- {slot.human()}" for slot in slots[:30]]
        return self.send("\n".join(lines), title, priority="low", tags=["x"])

    def notify_failure(self, message: str, failures: int) -> bool:
        title = f"⚠️ 빈자리 확인 실패 {failures}회 연속"
        body = f"확인이 계속 실패하고 있습니다. 로그인 세션이 만료됐을 수 있습니다.\n\n```\n{message[:600]}\n```"
        return self.send(body, title, priority="high", tags=["warning"])

    def notify_recovered(self) -> bool:
        return self.send("빈자리 확인이 다시 정상 동작합니다.", "✅ 감시 복구됨", priority="low", tags=["white_check_mark"])

    def notify_heartbeat(self, hall_name: str, slot_count: int) -> bool:
        body = f"감시는 정상 동작 중입니다. 현재 예약 가능 슬롯 {slot_count}건."
        return self.send(body, f"💓 {hall_name} 감시 중", priority="min", tags=["heartbeat"])


def _encode_header(value: str) -> str:
    """ASCII 가 아니면 RFC 2047 (=?UTF-8?B?...?=) 로 인코딩한다."""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        import base64

        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return f"=?UTF-8?B?{encoded}?="
