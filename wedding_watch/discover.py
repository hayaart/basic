"""로그인 세션 저장과 실제 API 엔드포인트 캡처 도구.

삼성카드 결혼도움방은 임직원 로그인이 필요하고 내부 API 주소가 공개돼 있지 않다.
그래서 처음 한 번은 사람이 직접 브라우저로 로그인/탐색하고, 그때 오간 요청을
캡처해서 config 에 넣을 값을 뽑아낸다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATE_RE = re.compile(r"^(\d{4}-?\d{2}-?\d{2})")
YN_VALUES = {"y", "n", "yes", "no", "true", "false", "가능", "불가", "마감"}
STATIC_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".woff2", ".ico")


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 설치 환경 의존
        raise SystemExit(
            "이 명령에는 Playwright 가 필요합니다:\n"
            "  pip install 'wedding-watch[browser]'\n"
            "  playwright install chromium"
        ) from exc
    return sync_playwright


def save_login(login_url: str, storage_state: str | Path, timeout_minutes: int = 15) -> Path:
    """브라우저를 띄워 직접 로그인하게 하고, 끝나면 쿠키를 저장한다."""
    sync_playwright = _require_playwright()
    storage_state = Path(storage_state)
    storage_state.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")
        print()
        print("=" * 68)
        print(" 브라우저에서 결혼도움방에 로그인하세요.")
        print(" 로그인 후 예식장 예약(달력) 화면까지 이동해 두면 더 좋습니다.")
        print(f" 끝나면 이 터미널에서 Enter 를 누르세요. (최대 {timeout_minutes}분)")
        print("=" * 68)
        input(" 완료했으면 Enter > ")
        context.storage_state(path=str(storage_state))
        browser.close()

    print(f"\n세션을 저장했습니다: {storage_state}")
    print("이 파일에는 로그인 쿠키가 들어 있습니다. 절대 공유하거나 커밋하지 마세요.")
    return storage_state


def capture_requests(
    start_url: str, storage_state: str | Path, out_dir: str | Path
) -> Path:
    """브라우저를 띄워 사용자가 탐색하는 동안 JSON 응답을 모두 기록한다."""
    sync_playwright = _require_playwright()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    storage_state = Path(storage_state)
    captured: list[dict[str, Any]] = []

    def on_response(response):
        url = response.url
        if url.lower().split("?")[0].endswith(STATIC_SUFFIXES):
            return
        content_type = (response.headers or {}).get("content-type", "")
        if "json" not in content_type.lower():
            return
        try:
            payload = response.json()
        except Exception:
            return
        request = response.request
        entry = {
            "url": url,
            "method": request.method,
            "status": response.status,
            "request_headers": {
                k: v
                for k, v in (request.headers or {}).items()
                # 쿠키/인증 헤더는 기록하지 않는다.
                if k.lower() not in {"cookie", "authorization"}
            },
            "post_data": request.post_data,
            "payload": payload,
        }
        captured.append(entry)
        print(f"  [캡처] {request.method} {url[:90]}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context_args = {}
        if storage_state.exists():
            context_args["storage_state"] = str(storage_state)
        context = browser.new_context(**context_args)
        context.on("response", on_response)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        print()
        print("=" * 68)
        print(" 브라우저에서 삼성금융연수원 예약 달력을 열고,")
        print(" 2027년 5월 → 6월 … 처럼 월을 몇 번 넘겨 보세요.")
        print(" 그동안 오간 JSON 요청을 기록합니다.")
        print(" 끝나면 이 터미널에서 Enter 를 누르세요.")
        print("=" * 68)
        input(" 완료했으면 Enter > ")
        # 탐색 중 로그인이 갱신됐을 수 있으니 세션도 다시 저장한다.
        context.storage_state(path=str(storage_state))
        browser.close()

    report_path = out_dir / "captured.json"
    report_path.write_text(
        json.dumps(captured, ensure_ascii=False, indent=2)[:20_000_000], encoding="utf-8"
    )
    print(f"\nJSON 응답 {len(captured)}건을 기록했습니다: {report_path}")

    suggestions = suggest_configs(captured)
    if suggestions:
        suggestion_path = out_dir / "suggested_config.yaml"
        suggestion_path.write_text(render_suggestions(suggestions), encoding="utf-8")
        print(f"추천 설정을 만들었습니다: {suggestion_path}")
        print("config.yaml 의 source.api 부분에 붙여 넣고 값을 확인하세요.")
    else:
        print("날짜가 들어 있는 응답을 찾지 못했습니다.")
        print("captured.json 을 직접 열어 보거나, source.mode 를 browser 로 바꿔 쓰세요.")
    return report_path


# --- 응답 분석 ---------------------------------------------------------


def _looks_like_date(value: Any) -> bool:
    if isinstance(value, (int, float)):
        value = str(int(value))
    if not isinstance(value, str):
        return False
    digits = re.sub(r"\D", "", value)
    if len(digits) == 8 and digits.startswith(("19", "20")):
        return True
    return bool(DATE_RE.match(value.strip()))


def find_record_lists(data: Any, path: str = "") -> list[tuple[str, list[dict]]]:
    """JSON 안에서 '딕셔너리들의 목록'을 모두 찾는다."""
    found: list[tuple[str, list[dict]]] = []
    if isinstance(data, list):
        if data and all(isinstance(item, dict) for item in data):
            found.append((path, data))
        for index, item in enumerate(data[:3]):
            found.extend(find_record_lists(item, f"{path}.{index}" if path else str(index)))
    elif isinstance(data, dict):
        for key, value in data.items():
            found.extend(find_record_lists(value, f"{path}.{key}" if path else key))
    return found


def analyze_records(records: list[dict]) -> dict[str, Any] | None:
    """레코드 목록에서 날짜 필드와 상태 필드 후보를 고른다."""
    sample = records[:50]
    date_fields = []
    status_fields = []
    time_fields = []
    for key in sample[0]:
        values = [row.get(key) for row in sample if isinstance(row, dict)]
        non_empty = [v for v in values if v not in (None, "")]
        if not non_empty:
            continue
        if all(_looks_like_date(v) for v in non_empty):
            date_fields.append(key)
            continue
        text_values = {str(v).strip().lower() for v in non_empty}
        if text_values <= YN_VALUES:
            status_fields.append((key, sorted({str(v).strip() for v in non_empty})))
        elif all(re.match(r"^\d{1,2}[:시]\d{0,2}", str(v).strip()) for v in non_empty):
            time_fields.append(key)
    if not date_fields:
        return None
    return {
        "date_field": date_fields[0],
        "other_date_fields": date_fields[1:],
        "status_candidates": status_fields,
        "time_candidates": time_fields,
        "sample": sample[0],
        "count": len(records),
    }


def suggest_configs(captured: list[dict]) -> list[dict[str, Any]]:
    suggestions = []
    for entry in captured:
        for path, records in find_record_lists(entry["payload"]):
            analysis = analyze_records(records)
            if analysis is None:
                continue
            suggestions.append({"entry": entry, "items_path": path, **analysis})
    # 레코드가 많은 응답이 달력일 가능성이 높다.
    suggestions.sort(key=lambda s: s["count"], reverse=True)
    return suggestions[:5]


def render_suggestions(suggestions: list[dict[str, Any]]) -> str:
    lines = [
        "# `wedding-watch discover` 가 캡처한 요청에서 자동으로 뽑은 후보입니다.",
        "# 가장 위 후보부터 확인하고, 맞는 것을 config.yaml 의 source.api 로 옮기세요.",
        "# 날짜/홀코드 부분은 {year}, {month}, {ym}, {hall_code} 로 바꿔야 매달 조회됩니다.",
        "",
    ]
    for index, suggestion in enumerate(suggestions, start=1):
        entry = suggestion["entry"]
        status = suggestion["status_candidates"]
        lines += [
            f"# --- 후보 {index}: 레코드 {suggestion['count']}건 ---",
            f"# 예시 레코드: {json.dumps(suggestion['sample'], ensure_ascii=False)[:300]}",
        ]
        if entry.get("post_data"):
            lines.append(f"# POST 본문: {str(entry['post_data'])[:300]}")
        lines += [
            "# api:",
            f"#   url: {entry['url'].split('?')[0]!r}",
            f"#   method: {entry['method']}",
            "#   params: {}   # 캡처된 쿼리스트링: " + (entry["url"].split("?", 1)[1][:200] if "?" in entry["url"] else "(없음)"),
            "#   response:",
            f"#     items_path: {suggestion['items_path']!r}",
            f"#     date_field: {suggestion['date_field']!r}",
        ]
        if suggestion["time_candidates"]:
            lines.append(f"#     time_field: {suggestion['time_candidates'][0]!r}")
        if status:
            field, values = status[0]
            lines.append(f"#     status_field: {field!r}")
            lines.append(f"#     available_values: {values!r}   # 이 중 '예약 가능'에 해당하는 값만 남기세요")
        lines.append("")
    return "\n".join(lines)
