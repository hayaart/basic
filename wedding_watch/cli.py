"""명령줄 인터페이스."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .adapters import FetchError, LoginRequired
from .config import Config, ConfigError, load_config
from .models import sort_slots
from .notify import Notifier
from .state import SeenState
from .watcher import Watcher

DEFAULT_CONFIG = "config.yaml"


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def load_dotenv(path: str | Path = ".env") -> None:
    """의존성 없이 .env 를 읽어 환경변수로 넣는다 (이미 있는 값은 유지)."""
    import os

    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wedding-watch",
        description="삼성카드 결혼도움방 웨딩홀 빈자리 감시 & ntfy 알림",
    )
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="설정 파일 경로")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="설정한 간격으로 계속 감시 (기본 10분)")
    once = sub.add_parser("check", help="한 번만 확인하고 종료 (cron 용)")
    once.add_argument("--dry-run", action="store_true", help="알림을 보내지 않고 결과만 출력")
    sub.add_parser("login", help="브라우저를 띄워 로그인하고 세션 쿠키 저장")

    discover = sub.add_parser("discover", help="실제 예약 API 요청을 캡처해 설정 후보 생성")
    discover.add_argument("--url", help="브라우저를 시작할 주소 (기본: 설정의 login_url)")
    discover.add_argument("--out", default="discover", help="캡처 결과를 저장할 디렉터리")

    sub.add_parser("test-notify", help="ntfy 설정이 맞는지 테스트 알림 발송")
    sub.add_parser("state", help="현재 기억 중인 빈자리 상태 출력")
    return parser


def cmd_run(config: Config) -> int:
    return Watcher(config).run_forever()


def cmd_check(config: Config, dry_run: bool) -> int:
    watcher = Watcher(config)
    try:
        if dry_run:
            result = watcher.check_once()
        else:
            result = watcher.run_once()
            if result is None:
                print("확인에 실패했습니다. 로그를 보세요.", file=sys.stderr)
                return 1
    except (FetchError, LoginRequired) as exc:
        print(f"확인 실패: {exc}", file=sys.stderr)
        return 1
    finally:
        watcher.adapter.close()

    print(f"\n대상: {config.target.hall_name} (홀 코드 {config.target.hall_code})")
    print(f"대상 월: {', '.join(config.target.months)}")
    print(f"예약 가능 슬롯 {len(result.slots)}건" + (" (알림 미발송)" if dry_run else ""))
    for slot in sort_slots(result.slots):
        mark = "NEW " if slot in result.new else "    "
        print(f"  {mark}{slot.human()}")
    if result.errors:
        print("\n일부 월 조회 실패:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
    return 0


def cmd_login(config: Config) -> int:
    from .discover import save_login

    save_login(config.source.login_url, config.source.storage_state)
    return 0


def cmd_discover(config: Config, url: str | None, out: str) -> int:
    from .discover import capture_requests

    capture_requests(url or config.source.login_url, config.source.storage_state, out)
    return 0


def cmd_test_notify(config: Config) -> int:
    notifier = Notifier(config.ntfy)
    ok = notifier.send(
        f"**{config.target.hall_name}** 감시 설정 테스트입니다.\n\n"
        f"- 홀 코드: {config.target.hall_code}\n"
        f"- 대상 월: {', '.join(config.target.months)}\n"
        f"- 확인 주기: {config.poll.interval_seconds // 60}분",
        "🔔 알림 테스트",
        priority="default",
    )
    print("전송 성공" if ok else "전송 실패 — ntfy 주소/토픽을 확인하세요.")
    return 0 if ok else 1


def cmd_state(config: Config) -> int:
    state = SeenState(config.state_file)
    print(f"상태 파일: {state.path}")
    print(f"기억 중인 빈자리: {len(state.seen)}건")
    for key in sorted(state.seen):
        entry = state.seen[key]
        print(f"  {key}  최초 {entry.get('first_seen')}  최근 {entry.get('last_seen')}")
    print(f"\n연속 실패: {state.meta.get('consecutive_failures', 0)}회")
    if state.meta.get("last_error"):
        print(f"마지막 오류: {state.meta['last_error']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    load_dotenv()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2

    if args.command == "run":
        return cmd_run(config)
    if args.command == "check":
        return cmd_check(config, args.dry_run)
    if args.command == "login":
        return cmd_login(config)
    if args.command == "discover":
        return cmd_discover(config, args.url, args.out)
    if args.command == "test-notify":
        return cmd_test_notify(config)
    if args.command == "state":
        return cmd_state(config)
    raise AssertionError(f"처리되지 않은 명령: {args.command}")
