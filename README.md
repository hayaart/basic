# 웨딩홀 빈자리 알림 (삼성카드 결혼도움방 · 삼성금융연수원)

삼성카드 결혼도움방의 **삼성금융연수원(홀 코드 5)** 예약 달력을 **10분마다** 확인해서,
**2027년 5·6·9·10·11월**에 빈자리가 새로 나오면 **ntfy 푸시**로 즉시 알려줍니다.

- 같은 빈자리는 **한 번만** 알립니다. 사라졌다가 다시 나오면 다시 알립니다.
- 세션이 만료되면 **스스로 다시 로그인**합니다. 그래도 계속 실패하면 **"점검 필요" 알림**을 보내서, 조용히 못 보고 지나치는 일을 막습니다.
- 매번 ±60초 흔들어(jitter) 초 단위로 똑같은 시각에 때리지 않습니다.

---

> 🙋 **개발을 모르신다면 → [사용설명서.md](사용설명서.md) 를 보세요.**
> 터미널 명령 복사·붙여넣기 수준으로 따라 할 수 있게 따로 썼습니다. 아래는 개발자용 문서입니다.

> 💻 **PC를 계속 켜두기 싫다면 → [apps-script/README.md](apps-script/README.md) 를 보세요.**
> 같은 감시를 구글 서버에서 돌리는 Google Apps Script 버전입니다. 설치도 복사·붙여넣기 5분이면 끝납니다.
> (단, 구글 서버 IP에서 접속하므로 사이트가 국내 IP만 허용하면 못 씁니다. 해당 문서 4단계에서 확인합니다.)

## ⚠️ 먼저 읽어주세요 — 한 단계는 직접 하셔야 합니다

결혼도움방(`s-wedding.samsungcard.com`)은 **삼성 임직원 로그인 전용**이고, 예약 달력을 그리는
내부 API 주소는 공개돼 있지 않습니다. 그래서 다음 두 가지는 **처음 한 번 사용자가 직접** 해야 합니다.

1. `wedding-watch login` — 브라우저로 직접 로그인 (쿠키를 저장해 이후 자동 조회에 씁니다)
2. `wedding-watch discover` — 달력을 넘겨보는 동안 오간 요청을 캡처 → **설정값 자동 추천**

이 두 단계만 마치면 나머지는 전부 자동입니다. (아래 [3단계](#3-실제-api-주소-찾기-discover) 참고)

---

## 빠른 시작

```bash
git clone https://github.com/hayaart/basic.git wedding-watch && cd wedding-watch

# 맥 / 리눅스
bash install.sh
# 윈도우 (PowerShell)
powershell -ExecutionPolicy Bypass -File .\install.ps1

./.venv/bin/wedding-watch setup        # 대화형 설정 (config.yaml + .env 생성)
./.venv/bin/wedding-watch test-notify  # 폰에 알림 확인
./.venv/bin/wedding-watch discover     # 브라우저에서 로그인 + 달력 넘기기 → 설정 자동 완성
./.venv/bin/wedding-watch run          # 감시 시작
```

> 윈도우는 실행 파일 경로가 다릅니다: `.venv\Scripts\wedding-watch setup`

`setup` 이 임의의 ntfy 토픽을 만들어 주고, `discover` 가 캡처한 요청을 `config.yaml` 에 바로 써 넣습니다.
수동으로 하고 싶다면 아래를 참고하세요.

## 수동 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[browser,dev]"
playwright install chromium          # login / discover / browser 모드에 필요
cp config.example.yaml config.yaml && cp .env.example .env
```

`.env` 의 `WW_NTFY_TOPIC` 을 **남이 절대 못 맞출 임의 문자열**로 바꾸세요.
ntfy 토픽은 이름을 아는 사람이면 누구나 구독할 수 있습니다.

휴대폰에 **ntfy 앱**([iOS](https://apps.apple.com/app/ntfy/id1625396347) /
[Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy))을 설치하고 같은 토픽을 구독한 뒤:

```bash
wedding-watch test-notify        # 폰에 알림이 오면 성공
```

## 2. 로그인 세션 저장

```bash
wedding-watch login
```

브라우저가 열립니다. 결혼도움방에 로그인하고 예약 달력까지 들어간 뒤 터미널에서 Enter.
쿠키가 `state/storage_state.json` 에 저장됩니다. **이 파일은 절대 커밋/공유하지 마세요** (`.gitignore` 에 이미 포함).

쿠키는 보통 며칠이면 풀립니다. 매번 수동으로 다시 로그인하기 싫다면
[자동 재로그인](#자동-재로그인-권장)을 켜세요.

## 3. 실제 API 주소 찾기 (`discover`)

```bash
wedding-watch discover
```

브라우저가 열리면 **로그인**하고, **삼성금융연수원 예약 달력**에서 **2027년 5월 → 6월 → 9월…** 처럼
월을 몇 번 넘겨보세요. 그동안 오간 JSON 요청을 전부 기록하고, "날짜 목록처럼 생긴" 응답을 골라
**`config.yaml` 의 `source.api` 와 `source.login` 을 자동으로 채웁니다.**

```
discover/captured.json          # 캡처된 원본 (쿠키·인증 헤더는 제외하고 저장)
discover/suggested_config.yaml  # 후보 목록 (자동 반영이 틀렸을 때 참고용)
discover/suggested_login.yaml   # 로그인 폼 후보 (필드 이름만, 값은 저장 안 함)
```

`--no-apply` 를 주면 `config.yaml` 을 건드리지 않고 추천 파일만 만듭니다. 그때는 아래처럼
날짜·홀코드를 자리표시자로 직접 바꿔 주세요 — 그래야 매달 자동으로 조회됩니다.

| 자리표시자 | 값 (2027년 5월 기준) |
|---|---|
| `{hall_code}` | `5` |
| `{year}` | `2027` |
| `{month}` | `05` |
| `{ym}` | `202705` |
| `{year_month}` | `2027-05` |

예시:

```yaml
source:
  mode: "api"
  api:
    url: "https://s-wedding.samsungcard.com/hall/selectHallSchedule.json"
    method: "POST"
    body:
      WEDG_HLL_C: "{hall_code}"
      SRCH_YM: "{ym}"
    response:
      items_path: "data.list"
      date_field: "WEDG_YMD"
      time_field: "WEDG_TM"
      status_field: "RSVT_PSBL_YN"
      available_values: ["Y"]
```

> **API 를 못 찾겠다면** `source.mode: "browser"` 로 바꾸세요. Playwright 로 달력 화면을 직접 렌더링해서
> `day_selector` 에 걸리는 셀을 빈자리로 읽습니다. 느리지만 확실합니다.

설정이 맞는지 확인:

```bash
wedding-watch check --dry-run    # 조회만 하고 알림은 보내지 않음
```

## 4. 감시 시작

```bash
wedding-watch run                # 10분마다 계속 확인 (Ctrl+C 로 종료)
```

---

## 명령어

| 명령 | 설명 |
|---|---|
| `wedding-watch setup` | 대화형 초기 설정 (여기서 시작) |
| `wedding-watch run` | 설정한 간격으로 계속 감시 |
| `wedding-watch check` | 한 번만 확인 (cron 용) |
| `wedding-watch check --dry-run` | 확인만 하고 알림·상태 저장 안 함 |
| `wedding-watch login` | 브라우저 로그인 후 세션 저장 |
| `wedding-watch discover` | 실제 API 요청 캡처 → 설정 후보 생성 |
| `wedding-watch test-notify` | ntfy 설정 테스트 |
| `wedding-watch test-login` | 자동 재로그인 설정 테스트 |
| `wedding-watch test-public` | 로그인 없이도 조회되는지 실제로 확인 |
| `wedding-watch state` | 지금 기억 중인 빈자리 목록 |

## 설정 항목

주요 항목만 추렸습니다. 전체는 [`config.example.yaml`](config.example.yaml) 에 주석과 함께 있습니다.

| 키 | 기본값 | 설명 |
|---|---|---|
| `target.hall_code` | `"5"` | 삼성금융연수원 홀 코드 |
| `target.months` | 2027-05/06/09/10/11 | 노리는 예식 월 |
| `target.weekdays` | `[]` (전 요일) | 예: `[5, 6]` → 토·일만 |
| `target.exclude_dates` | `[]` | 제외할 날짜 |
| `poll.interval_seconds` | `600` | 확인 주기 (최소 60) |
| `poll.failure_alert_after` | `3` | 연속 실패 N회에 점검 알림 |
| `poll.notify_on_disappear` | `false` | 빈자리 마감도 알릴지 |
| `poll.heartbeat_hours` | `0` | N시간마다 생존 알림 (0=끔) |

환경변수로도 덮어쓸 수 있습니다: `WW_NTFY_TOPIC`, `WW_NTFY_TOKEN`, `WW_HALL_CODE`,
`WW_MONTHS`, `WW_INTERVAL_SECONDS`, `WW_SOURCE_MODE` …

## 로그인이 정말 필요한가?

결혼도움방은 회원 전용 사이트지만, 달력 API 자체가 인증을 확인하는지는 **측정해 봐야** 압니다.

```bash
wedding-watch test-public
```

저장된 쿠키와 자동 로그인을 모두 끈 채로 같은 요청을 보내 봅니다.

- **로그인 없이도 조회됩니다** → `source.login.enabled` 를 `false` 로 두세요. 아이디/비밀번호가 아예 필요 없습니다.
- **로그인이 필요합니다** → 아래 자동 재로그인을 켜세요.
- **판단 불가** → 서버 오류 등으로 구분이 안 된 경우입니다. 브라우저 시크릿 창으로 직접 확인해 보세요.

## 자동 재로그인 (권장)

결혼도움방은 임직원 SSO 가 아니라 **사이트 자체 아이디/비밀번호 폼 로그인**이라, 세션이 만료되면
앱이 알아서 다시 로그인할 수 있습니다. 이걸 켜두면 손 댈 일이 없어집니다.

`discover` 를 실행할 때 **브라우저에서 로그인까지 직접 하면**, 로그인 폼의 **필드 이름만**
기록해 `discover/suggested_login.yaml` 로 뽑아 줍니다. (아이디·비밀번호 **값은 저장하지 않습니다.**)

그 내용을 `config.yaml` 에 옮기고:

```yaml
source:
  login:
    enabled: true
    url: "https://s-wedding.samsungcard.com/login/loginProc.do"   # 폼이 POST 하는 주소
    method: "POST"
    form:
      userId: "{id}"          # ← 실제 필드명으로
      userPw: "{password}"
```

아이디/비밀번호는 **`config.yaml` 이 아니라 `.env`** 에 넣습니다 (`config.yaml` 은 `.gitignore` 에 있지만,
습관적으로 비밀값은 분리해 두는 편이 안전합니다):

```bash
WW_LOGIN_ID=your-id
WW_LOGIN_PW=your-password
```

확인:

```bash
wedding-watch test-login
```

동작 방식: 조회가 로그인 페이지로 튕기면 → 자동으로 한 번 로그인 → 같은 조회를 재시도.
갱신된 쿠키는 `state/storage_state.json` 에 다시 저장돼서, 다음 실행(cron 포함)은 로그인 없이 바로 씁니다.

> **비밀번호가 틀리면 재시도하지 않고 즉시 멈춥니다.** 10분마다 틀린 비밀번호로 계속 두드리면
> 계정이 잠기기 때문입니다. 이때는 "⚠️ 확인 실패" 알림이 오니 `.env` 를 고치면 됩니다.

`browser` 모드에서도 됩니다. 이때는 `url`/`form` 대신 선택자를 씁니다:

```yaml
    id_selector: "#userId"
    password_selector: "#userPw"
    submit_selector: "#btnLogin"
```

## 계속 띄워두기

**systemd** (리눅스 서버/라즈베리파이):

```bash
sudo cp deploy/wedding-watch.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now wedding-watch
journalctl -u wedding-watch -f
```

**Docker**:

```bash
docker compose -f docker/compose.yaml up -d
```

**cron** (10분마다 `check` 한 번씩):

```cron
*/10 * * * * cd /path/to/wedding-watch && .venv/bin/wedding-watch check >> logs/cron.log 2>&1
```

> GitHub Actions 같은 공용 러너에서 돌리는 건 권장하지 않습니다. 로그인 쿠키를 시크릿에 넣어야 하는데
> 세션이 만료되면 매번 다시 넣어야 하고, 임직원 계정 쿠키를 외부에 두는 위험도 있습니다.

## 세션이 만료되면

[자동 재로그인](#자동-재로그인-권장)을 켰다면 앱이 알아서 처리합니다.

켜지 않았다면 쿠키가 풀린 뒤 연속 실패가 `failure_alert_after` 회에 도달하면
**"⚠️ 빈자리 확인 실패" 푸시**가 오니, 그때 `wedding-watch login` 을 다시 실행하면 됩니다.
복구되면 "✅ 감시 복구됨" 알림이 한 번 옵니다.

## 예의에 관하여

10분 간격(하루 약 144회 × 대상 월 5개)은 사람이 브라우저로 새로고침하는 것과 비슷한 수준이지만,
`interval_seconds` 를 더 짧게 줄이지는 마세요. 설정 검증에서 60초 미만은 거부합니다.
이 도구는 **공개된 예약 화면을 대신 새로고침해 줄 뿐**이고, 예약을 대신 잡아주지는 않습니다.

## 개발

```bash
pip install -e ".[dev]"
pytest -q
```

## 구조

```
wedding_watch/
  cli.py          명령줄 진입점
  config.py       YAML + 환경변수 설정 로딩/검증
  models.py       Slot (날짜·시간대) 및 날짜 정규화
  state.py        이미 알린 빈자리 기억 (원자적 저장)
  notify.py       ntfy 전송 (한글 제목 RFC2047 인코딩)
  watcher.py      감시 루프: 조회 → 비교 → 알림
  discover.py     로그인 세션 저장 + API/로그인폼 캡처 및 분석
  autoconfig.py   캡처 결과를 config.yaml 에 자동 반영
  probe.py        로그인이 실제로 필요한지 측정
  setup_wizard.py 대화형 초기 설정
  adapters/
    api.py        내부 JSON API 직접 호출 (기본) + 자동 재로그인
    browser.py    Playwright 로 달력 렌더링해 읽기
```
