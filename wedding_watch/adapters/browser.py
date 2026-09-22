"""Playwright 로 실제 달력 화면을 렌더링해 읽는 어댑터.

API 엔드포인트를 못 찾았거나 화면이 JS 로만 그려질 때 쓴다. API 모드보다 무겁다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import SourceConfig
from ..models import Slot
from .base import Adapter, FetchError, LoginRequired, render, template_vars

log = logging.getLogger(__name__)

_DAY_RE = re.compile(r"\b([12]?\d|3[01])\b")


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 설치 환경 의존
        raise FetchError(
            "browser 모드에는 Playwright 가 필요합니다: "
            "pip install 'wedding-watch[browser]' && playwright install chromium"
        ) from exc
    return sync_playwright


class BrowserAdapter(Adapter):
    def __init__(self, source: SourceConfig, hall_code: str, timeout: int = 30):
        self.source = source
        self.browser_cfg = source.browser
        self.hall_code = hall_code
        self.timeout_ms = timeout * 1000
        self._pw = None
        self._browser = None
        self._context = None

    def _ensure_context(self):
        if self._context is not None:
            return self._context
        sync_playwright = _require_playwright()
        storage = Path(self.source.storage_state)
        if not storage.exists():
            raise LoginRequired(
                f"저장된 로그인 세션이 없습니다: {storage}\n"
                "`wedding-watch login` 을 먼저 실행해 로그인하세요."
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.browser_cfg.headless)
        self._context = self._browser.new_context(storage_state=str(storage))
        self._context.set_default_timeout(self.timeout_ms)
        return self._context

    def fetch_month(self, year: int, month: int) -> list[Slot]:
        context = self._ensure_context()
        variables = template_vars(self.hall_code, year, month)
        url = render(self.browser_cfg.url_template, variables)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            if self._looks_like_login(page.url, page.content()):
                raise LoginRequired(
                    "로그인 화면으로 이동했습니다. `wedding-watch login` 으로 세션을 갱신하세요."
                )
            if self.browser_cfg.wait_selector:
                try:
                    page.wait_for_selector(self.browser_cfg.wait_selector, timeout=self.timeout_ms)
                except Exception as exc:
                    raise FetchError(
                        f"wait_selector({self.browser_cfg.wait_selector!r}) 를 찾지 못했습니다: {exc}"
                    ) from exc
            if self.browser_cfg.extra_wait_ms:
                page.wait_for_timeout(self.browser_cfg.extra_wait_ms)
            return self._read_slots(page, year, month)
        finally:
            page.close()

    def _looks_like_login(self, url: str, body: str) -> bool:
        haystack = f"{url}\n{body[:3000]}".lower()
        return any(
            marker.lower() in haystack for marker in self.source.login_required_markers if marker
        )

    def _read_slots(self, page, year: int, month: int) -> list[Slot]:
        cells = page.query_selector_all(self.browser_cfg.day_selector)
        slots: list[Slot] = []
        for cell in cells:
            date = self._cell_date(cell, year, month)
            if date is None:
                continue
            times = self._cell_times(cell)
            label = (cell.inner_text() or "").strip().replace("\n", " ")[:60]
            if times:
                slots.extend(Slot(date=date, time=t, label=label) for t in times)
            else:
                slots.append(Slot(date=date, label=label))
        return slots

    def _cell_date(self, cell, year: int, month: int) -> str | None:
        if self.browser_cfg.date_attr:
            raw = cell.get_attribute(self.browser_cfg.date_attr)
            if not raw:
                return None
            digits = re.sub(r"\D", "", raw)
            if len(digits) >= 8:
                return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
            if digits.isdigit() and 1 <= int(digits) <= 31:
                return f"{year:04d}-{month:02d}-{int(digits):02d}"
            log.warning("date_attr 값을 해석하지 못했습니다: %r", raw)
            return None
        match = _DAY_RE.search((cell.inner_text() or "").strip())
        if not match:
            return None
        return f"{year:04d}-{month:02d}-{int(match.group(1)):02d}"

    def _cell_times(self, cell) -> list[str]:
        if not self.browser_cfg.time_selector:
            return []
        times = []
        for node in cell.query_selector_all(self.browser_cfg.time_selector):
            text = (node.inner_text() or "").strip()
            if text:
                times.append(text)
        return times

    def close(self) -> None:
        for resource, name in ((self._context, "context"), (self._browser, "browser"), (self._pw, "playwright")):
            if resource is None:
                continue
            try:
                resource.stop() if name == "playwright" else resource.close()
            except Exception as exc:  # pragma: no cover - 정리 중 오류는 무시
                log.debug("%s 정리 중 오류: %s", name, exc)
        self._context = self._browser = self._pw = None
