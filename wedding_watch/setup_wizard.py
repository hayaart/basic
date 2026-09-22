"""처음 설정을 대화형으로 만들어 준다 (YAML 을 손으로 안 고쳐도 되게)."""

from __future__ import annotations

import os
import re
import secrets
import stat
from pathlib import Path

import yaml

DEFAULT_MONTHS = ["2027-05", "2027-06", "2027-09", "2027-10", "2027-11"]

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def ask_nonempty(question: str, default: str = "") -> str:
    """빈 값을 허용하지 않는다."""
    while True:
        answer = ask(question, default)
        if answer:
            return answer
        print("    → 값을 입력해 주세요.")


def ask_months(question: str, default: list[str]) -> list[str]:
    """YYYY-MM 형식이 맞을 때까지 다시 물어본다.

    형식이 틀리면 나중에 조회 단계에서야 실패하는데, 그때는 원인을 찾기 어렵다.
    """
    while True:
        raw = ask(question, ", ".join(default))
        months = [m.strip() for m in raw.split(",") if m.strip()]
        bad = [m for m in months if not MONTH_RE.match(m)]
        if months and not bad:
            return months
        if bad:
            print(f"    → 형식이 올바르지 않습니다: {', '.join(bad)}")
        print("    → '2027-05' 처럼 연도-월 로, 여러 개면 쉼표로 구분해 주세요.")


def ask_yes_no(question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = input(f"{question} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "네", "ㅇ"}


def generate_topic() -> str:
    """남이 못 맞추는 ntfy 토픽 이름을 만든다."""
    return f"wedding-{secrets.token_hex(6)}"


def write_env(env_path: Path, values: dict[str, str]) -> None:
    """기존 값은 살리고 주어진 항목만 갱신한 뒤, 본인만 읽을 수 있게 잠근다."""
    lines: list[str] = []
    seen: set[str] = set()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip()
            if key in values:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                lines.append(line)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)  # 600


def run_setup(config_path: str | Path, example_path: str | Path, env_path: str | Path) -> int:
    config_path, example_path, env_path = Path(config_path), Path(example_path), Path(env_path)

    print()
    print("=" * 64)
    print(" 웨딩홀 빈자리 알림 - 처음 설정")
    print(" 물어보는 것만 답하시면 설정 파일이 자동으로 만들어집니다.")
    print(" 그냥 Enter 를 누르면 [] 안의 기본값이 쓰입니다.")
    print("=" * 64)
    print()

    if config_path.exists():
        if not ask_yes_no(f"{config_path} 가 이미 있습니다. 다시 만들까요?", default=False):
            print("취소했습니다.")
            return 0

    data = yaml.safe_load(example_path.read_text(encoding="utf-8")) or {}

    print("[1/4] 어느 웨딩홀인가요?")
    hall_name = ask_nonempty("  홀 이름", data["target"].get("hall_name", "삼성금융연수원"))
    hall_code = ask_nonempty("  홀 코드", str(data["target"].get("hall_code", "5")))

    print("\n[2/4] 언제 결혼하시나요? (쉼표로 구분, YYYY-MM)")
    months = ask_months("  대상 월", DEFAULT_MONTHS)

    weekends_only = ask_yes_no("  주말(토·일)만 볼까요?", default=False)

    print("\n[3/4] 얼마나 자주 확인할까요?")
    while True:
        minutes = ask("  확인 주기(분)", "10")
        try:
            interval = int(minutes) * 60
        except ValueError:
            print("    → 숫자로 입력해 주세요. 예: 10")
            continue
        if interval < 60:
            print("    → 너무 잦습니다. 1분 이상으로 해주세요.")
            continue
        break

    print("\n[4/4] 휴대폰 알림(ntfy) 설정")
    print("  토픽은 '알림 채널 이름'입니다. 이름을 아는 사람은 누구나 볼 수 있으니")
    print("  아무도 못 맞출 임의의 이름을 씁니다.")
    topic = ask("  토픽 이름", generate_topic())

    data["target"].update(
        {
            "hall_name": hall_name,
            "hall_code": hall_code,
            "months": months,
            "weekdays": [5, 6] if weekends_only else [],
        }
    )
    data["poll"]["interval_seconds"] = interval
    data["ntfy"]["topic"] = topic

    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )

    env_values = {"WW_NTFY_TOPIC": topic}
    print()
    if ask_yes_no("세션이 끊겨도 자동으로 다시 로그인할까요? (권장)", default=True):
        print("  아이디/비밀번호는 이 컴퓨터의 .env 파일에만 저장되고, 화면에는 보이지 않습니다.")
        import getpass

        login_id = ask("  결혼도움방 아이디")
        login_pw = getpass.getpass("  결혼도움방 비밀번호: ")
        if login_id and login_pw:
            env_values["WW_LOGIN_ID"] = login_id
            env_values["WW_LOGIN_PW"] = login_pw
    write_env(env_path, env_values)

    print()
    print("=" * 64)
    print(f" 설정 완료: {config_path}, {env_path}")
    print()
    print(" 다음 순서로 진행하세요:")
    print("   1. 휴대폰에 ntfy 앱을 설치하고 이 토픽을 구독하세요:")
    print(f"        {topic}")
    print("   2. wedding-watch test-notify    ← 폰에 알림이 오는지 확인")
    print("   3. wedding-watch discover       ← 브라우저에서 로그인하고 달력 넘기기")
    print("   4. wedding-watch run            ← 감시 시작")
    print("=" * 64)
    return 0
